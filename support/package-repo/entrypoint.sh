#!/usr/bin/env bash

# Function to handle shutdown signals
cleanup() {
    # Prevent multiple cleanup calls
    if [ "$CLEANUP_CALLED" = "true" ]; then
        return
    fi
    CLEANUP_CALLED=true
    
    echo "Shutting down services..."
    
    # Kill monitoring process if running
    if [ -n "$MONITOR_PID" ] && kill -0 "$MONITOR_PID" 2>/dev/null; then
        echo "Stopping monitoring process (PID: $MONITOR_PID)..."
        kill -TERM "$MONITOR_PID" 2>/dev/null || true
        # Give it a moment to shutdown gracefully
        sleep 2
        # Force kill if still running
        if kill -0 "$MONITOR_PID" 2>/dev/null; then
            echo "Force killing monitoring process..."
            kill -KILL "$MONITOR_PID" 2>/dev/null || true
        fi
        wait "$MONITOR_PID" 2>/dev/null || true
    fi
    
    # Stop nginx
    if [ -n "$NGINX_PID" ] && kill -0 "$NGINX_PID" 2>/dev/null; then
        echo "Stopping nginx (PID: $NGINX_PID)..."
        kill -TERM "$NGINX_PID" 2>/dev/null || true
        # Give nginx time to shutdown gracefully
        sleep 2
        # Force kill if still running
        if kill -0 "$NGINX_PID" 2>/dev/null; then
            echo "Force killing nginx..."
            kill -KILL "$NGINX_PID" 2>/dev/null || true
        fi
        wait "$NGINX_PID" 2>/dev/null || true
    fi
    
    echo "All services stopped"
    exit 0
}

# Set up signal handlers
trap cleanup SIGTERM SIGINT

# Check if monitoring should be enabled (default: yes)
ENABLE_MONITORING="${ENABLE_MONITORING:-true}"

# Run the repository setup script if a directory is mounted
if [ -d "/repo" ]; then
    if [ "$ENABLE_MONITORING" = "true" ]; then
        echo "Starting repository monitoring for /repo..."
        # Start repository monitoring in background
        /usr/local/bin/monitor-repo.sh /repo &
        MONITOR_PID=$!
        echo "Repository monitoring started with PID $MONITOR_PID"
    else
        echo "Setting up repositories from /repo (monitoring disabled)..."
        /usr/local/bin/setup-repo.sh /repo
    fi
else
    echo "Warning: No RPM directory mounted at /repo"
fi

# Start nginx in background
nginx -g "daemon off;" &
NGINX_PID=$!

echo "Services started - nginx: $NGINX_PID, monitor: ${MONITOR_PID:-none}"

# Wait for processes to exit (or be killed by signal handler)
# Use a loop to handle signals properly
while true; do
    # Check if nginx is still running
    if ! kill -0 "$NGINX_PID" 2>/dev/null; then
        echo "Nginx process ended"
        break
    fi
    
    # Check if monitoring is enabled and monitor process ended
    if [ "$ENABLE_MONITORING" = "true" ] && [ -n "$MONITOR_PID" ] && ! kill -0 "$MONITOR_PID" 2>/dev/null; then
        echo "Monitor process ended"
        break
    fi
    
    # Sleep briefly and check again
    sleep 1
done

# Clean exit
cleanup 
