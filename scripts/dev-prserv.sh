#!/usr/bin/env bash
# dev-prserv.sh: Manage PV server for development and CI
#
# Usage: 
#   ./scripts/dev-prserv.sh start [--network NETWORK] [--db-dir DIR]
#   ./scripts/dev-prserv.sh stop [--network NETWORK]
#   ./scripts/dev-prserv.sh status [--network NETWORK]
#   ./scripts/dev-prserv.sh logs [--network NETWORK]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source common functions if available
if [ -f "$SCRIPT_DIR/lib/common.sh" ]; then
    source "$SCRIPT_DIR/lib/common.sh"
fi

# Default values
DEFAULT_NETWORK="avocado-prserv-dev"
DEFAULT_DB_DIR="$PROJECT_ROOT/.prserv-data"
DEFAULT_CONTAINER_NAME="avocado-prserv-server"
DEFAULT_PORT="8585"
DEFAULT_USER_ID="$(id -u)"
DEFAULT_GROUP_ID="$(id -g)"
YOCTO_BUILD_IMAGE="avocadolinux/yocto-build:ubuntu-24.04"

# Parse arguments
COMMAND="${1:-help}"
NETWORK="$DEFAULT_NETWORK"
DB_DIR="$DEFAULT_DB_DIR"
CONTAINER_NAME="$DEFAULT_CONTAINER_NAME"
PORT="$DEFAULT_PORT"
USER_ID="$DEFAULT_USER_ID"
GROUP_ID="$DEFAULT_GROUP_ID"

shift || true
while [[ $# -gt 0 ]]; do
    case $1 in
        --network)
            NETWORK="$2"
            CONTAINER_NAME="avocado-prserv-$(echo "$NETWORK" | sed 's/[^a-zA-Z0-9]/-/g')"
            shift 2
            ;;
        --db-dir)
            DB_DIR="$2"
            shift 2
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --container-name)
            CONTAINER_NAME="$2"
            shift 2
            ;;
        --uid)
            USER_ID="$2"
            shift 2
            ;;
        --gid)
            GROUP_ID="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

show_help() {
    cat << EOF
PV Server Management Script

Usage: $0 COMMAND [OPTIONS]

Commands:
    start       Start PV server and network
    stop        Stop PV server and clean up network
    status      Show PV server status
    logs        Show PV server logs
    ping        Test PV server connectivity
    help        Show this help

Options:
    --network NAME      Docker network name (default: $DEFAULT_NETWORK)
    --db-dir DIR        Database directory (default: $DEFAULT_DB_DIR)
    --port PORT         PV server port (default: $DEFAULT_PORT)
    --container-name    Container name (default: $DEFAULT_CONTAINER_NAME)
    --uid UID           User ID for container (default: $DEFAULT_USER_ID)
    --gid GID           Group ID for container (default: $DEFAULT_GROUP_ID)

Examples:
    # Start PV server for development
    $0 start

    # Start with custom network (useful for CI)
    $0 start --network avocado-ci-\$(date +%s)

    # Check status
    $0 status

    # View logs
    $0 logs

    # Stop and cleanup
    $0 stop

Development Workflow:
    1. Start PV server: $0 start
    2. Run builds that connect to the PV server
    3. Check logs: $0 logs
    4. Stop when done: $0 stop
EOF
}

ensure_network() {
    if ! docker network ls --format "{{.Name}}" | grep -q "^${NETWORK}$"; then
        echo "Creating Docker network: $NETWORK"
        docker network create "$NETWORK"
    else
        echo "Docker network already exists: $NETWORK"
    fi
}

start_prserv() {
    echo "Starting PV server..."
    echo "  Network: $NETWORK"
    echo "  Container: $CONTAINER_NAME"
    echo "  Database: $DB_DIR"
    echo "  Port: $PORT"
    echo "  User ID: $USER_ID"
    echo "  Group ID: $GROUP_ID"
    echo "  Image: $YOCTO_BUILD_IMAGE"

    # Ensure network exists
    ensure_network

    # Create database directory
    mkdir -p "$DB_DIR"
    chmod 755 "$DB_DIR"

    # Check if container is already running
    if docker ps --filter "name=$CONTAINER_NAME" --filter "status=running" --quiet | grep -q .; then
        echo "PV server container is already running: $CONTAINER_NAME"
        return 0
    fi

    # Remove any stopped container with the same name
    if docker ps -a --filter "name=$CONTAINER_NAME" --quiet | grep -q .; then
        echo "Removing existing stopped container: $CONTAINER_NAME"
        docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    fi

    echo "Starting PV server container..."
    docker run -d --rm \
        --name "$CONTAINER_NAME" \
        --network "$NETWORK" \
        -p "${PORT}:${PORT}" \
        -e USER_ID="$USER_ID" -e GROUP_ID="$GROUP_ID" \
        -v "$PROJECT_ROOT:/avocado-build" \
        -v "$DB_DIR:/prserv-data" \
        -w /avocado-build \
        "$YOCTO_BUILD_IMAGE" \
        bash -c "
            echo 'Initializing PV server...'
            echo 'Working directory: \$(pwd)'
            echo 'Database directory: /prserv-data'
            
            # Initialize build environment using minimal PV server kas config
            echo 'Initializing build environment...'
            source ./scripts/init-build kas/prserv.yml
            source .envrc
            
            echo 'KAS_YML: '\$KAS_YML
            echo 'Starting bitbake PV server...'
            # Start PV server as daemon and then tail the log to keep container running
            kas shell \"\$KAS_YML\" -c \"bitbake-prserv --host=0.0.0.0 --port=$PORT --file=/prserv-data/cache.db --log=/prserv-data/prserv.log --loglevel=DEBUG --start\"
            
            echo 'PV server started, tailing log to keep container alive...'
            tail -f /prserv-data/prserv.log
        "

    # Wait for server to start
    echo "Waiting for PV server to start..."
    sleep 15

    # Verify server is running
    if docker ps --filter "name=$CONTAINER_NAME" --filter "status=running" --quiet | grep -q .; then
        echo "✅ PV server started successfully"
        echo "   Container: $CONTAINER_NAME"
        echo "   Network: $NETWORK"
        echo "   Host: $CONTAINER_NAME:$PORT (within network)"
        echo "   External: localhost:$PORT"
        
        # Show initial logs
        echo ""
        echo "Initial container logs:"
        docker logs "$CONTAINER_NAME" --tail 10
        
        # Test connectivity
        echo ""
        if ping_prserv_internal; then
            echo "✅ PV server is responding to ping"
        else
            echo "⚠️  PV server started but not responding to ping yet (may need more time)"
        fi
    else
        echo "❌ Failed to start PV server container"
        echo "Container logs:"
        docker logs "$CONTAINER_NAME" 2>/dev/null || echo "No logs available"
        return 1
    fi
}

stop_prserv() {
    echo "Stopping PV server..."

    # Stop container
    if docker ps --filter "name=$CONTAINER_NAME" --quiet | grep -q .; then
        echo "Stopping container: $CONTAINER_NAME"
        docker stop "$CONTAINER_NAME" || true
        echo "Container stopped (auto-removed due to --rm flag)"
    else
        echo "Container not running: $CONTAINER_NAME"
    fi

    # Only remove network if it's the default development network
    if [ "$NETWORK" = "$DEFAULT_NETWORK" ]; then
        if docker network ls --format "{{.Name}}" | grep -q "^${NETWORK}$"; then
            # Check if any other containers are using the network
            CONTAINERS_ON_NETWORK=$(docker network inspect "$NETWORK" --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null || echo "")
            if [ -z "$CONTAINERS_ON_NETWORK" ]; then
                echo "Removing Docker network: $NETWORK"
                docker network rm "$NETWORK" || true
            else
                echo "Not removing network $NETWORK - other containers are using it: $CONTAINERS_ON_NETWORK"
            fi
        fi
    else
        echo "Not removing custom network: $NETWORK (remove manually if needed)"
    fi

    echo "PV server stopped"
}

status_prserv() {
    echo "PV Server Status:"
    echo "  Network: $NETWORK"
    echo "  Container: $CONTAINER_NAME"
    echo "  Database: $DB_DIR"
    echo "  Port: $PORT"
    echo "  User ID: $USER_ID"
    echo "  Group ID: $GROUP_ID"

    # Check network
    if docker network ls --format "{{.Name}}" | grep -q "^${NETWORK}$"; then
        echo "  ✅ Network exists: $NETWORK"
        
        # Show containers on network
        CONTAINERS_ON_NETWORK=$(docker network inspect "$NETWORK" --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null || echo "")
        if [ -n "$CONTAINERS_ON_NETWORK" ]; then
            echo "     Containers on network: $CONTAINERS_ON_NETWORK"
        else
            echo "     No containers on network"
        fi
    else
        echo "  ❌ Network missing: $NETWORK"
    fi

    # Check container
    if docker ps --filter "name=$CONTAINER_NAME" --filter "status=running" --quiet | grep -q .; then
        echo "  ✅ Container running: $CONTAINER_NAME"
        
        # Check database
        if [ -f "$DB_DIR/cache.db" ]; then
            DB_SIZE=$(du -h "$DB_DIR/cache.db" | cut -f1)
            echo "  ✅ Database exists: $DB_SIZE"
        else
            echo "  ⚠️  Database not found: $DB_DIR/cache.db"
        fi

        # Check log file
        if [ -f "$DB_DIR/prserv.log" ]; then
            LOG_SIZE=$(du -h "$DB_DIR/prserv.log" | cut -f1)
            LOG_LINES=$(wc -l < "$DB_DIR/prserv.log" 2>/dev/null || echo "0")
            echo "  ✅ Log file exists: $LOG_SIZE ($LOG_LINES lines)"
        else
            echo "  ⚠️  Log file not found: $DB_DIR/prserv.log"
        fi

        # Test connectivity
        if ping_prserv_internal; then
            echo "  ✅ PV server responding to ping"
        else
            echo "  ❌ PV server not responding to ping"
        fi
    else
        echo "  ❌ Container not running: $CONTAINER_NAME"
    fi
}

logs_prserv() {
    echo "=== Container Logs ==="
    if docker ps --filter "name=$CONTAINER_NAME" --quiet | grep -q .; then
        docker logs "$CONTAINER_NAME" --tail 50
    else
        echo "Container not running: $CONTAINER_NAME"
    fi

    echo ""
    echo "=== PV Server Log File ==="
    if [ -f "$DB_DIR/prserv.log" ]; then
        echo "Last 50 lines of $DB_DIR/prserv.log:"
        tail -50 "$DB_DIR/prserv.log"
    else
        echo "Log file not found: $DB_DIR/prserv.log"
    fi
}

ping_prserv_internal() {
    # Test from within the same network using a simple TCP connection
    # Just test if the port is open without sending data to avoid protocol errors
    docker run --rm --network "$NETWORK" \
        "$YOCTO_BUILD_IMAGE" \
        bash -c "
            # Try to connect to the PV server using bash TCP redirection (connection test only)
            timeout 3 bash -c 'exec 3<>/dev/tcp/$CONTAINER_NAME/$PORT && exec 3<&-' 2>/dev/null
        " 2>/dev/null || return 1
}

ping_prserv() {
    echo "Testing PV server connectivity..."
    
    if ping_prserv_internal; then
        echo "✅ PV server is responding"
    else
        echo "❌ PV server is not responding"
        return 1
    fi
}

# Main command dispatch
case "$COMMAND" in
    start)
        start_prserv
        ;;
    stop)
        stop_prserv
        ;;
    status)
        status_prserv
        ;;
    logs)
        logs_prserv
        ;;
    ping)
        ping_prserv
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo "Unknown command: $COMMAND"
        echo "Use '$0 help' for usage information"
        exit 1
        ;;
esac
