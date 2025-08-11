#!/usr/bin/env bash

# Don't exit on errors - we'll handle them explicitly

# Configuration
REPO_DIR="${1:-/repo}"
DONE_FILE="${REPO_DIR}/avocado-build.done"
MAP_FILE="${REPO_DIR}/avocado-repo.map"
SETUP_SCRIPT="/usr/local/bin/setup-repo.sh"
LOG_PREFIX="[DONE-MONITOR]"

# Configuration with environment variable overrides
CHECK_INTERVAL="${CHECK_INTERVAL:-2}"      # Seconds between checks for done file
LOG_LEVEL="${LOG_LEVEL:-INFO}"             # DEBUG, INFO, WARN, ERROR
DRY_RUN="${DRY_RUN:-false}"               # Set to true to log changes without updating

# State tracking
LAST_DONE_TIMESTAMP=""

# Logging functions
log_debug() { [[ "$LOG_LEVEL" == "DEBUG" ]] && echo "${LOG_PREFIX} DEBUG $(date '+%Y-%m-%d %H:%M:%S') $*"; }
log_info() { [[ "$LOG_LEVEL" =~ ^(DEBUG|INFO)$ ]] && echo "${LOG_PREFIX} INFO $(date '+%Y-%m-%d %H:%M:%S') $*"; }
log_warn() { [[ "$LOG_LEVEL" =~ ^(DEBUG|INFO|WARN)$ ]] && echo "${LOG_PREFIX} WARN $(date '+%Y-%m-%d %H:%M:%S') $*"; }
log_error() { echo "${LOG_PREFIX} ERROR $(date '+%Y-%m-%d %H:%M:%S') $*" >&2; }

# Function to get file modification timestamp
get_file_timestamp() {
    local file="$1"
    if [[ -f "$file" ]]; then
        stat -c %Y "$file" 2>/dev/null || echo "0"
    else
        echo "0"
    fi
}

# Function to trigger repository update
trigger_update() {
    local trigger_reason="$1"
    
    log_info "Triggering repository update: ${trigger_reason}"
    
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "DRY RUN: Would run ${SETUP_SCRIPT} ${REPO_DIR}"
        return 0
    fi
    
    # Verify map file exists (but don't fail completely if it doesn't)
    if [[ ! -f "${MAP_FILE}" ]]; then
        log_warn "Map file not found: ${MAP_FILE}"
        log_info "Skipping repository update until map file is available"
        return 1
    fi
    
    # Run the setup script to regenerate repositories
    local start_time
    start_time=$(date +%s)
    
    if "${SETUP_SCRIPT}" "${REPO_DIR}"; then
        local end_time
        end_time=$(date +%s)
        local duration=$((end_time - start_time))
        log_info "Repository update completed successfully in ${duration}s"
        
        # Archive the done file to prevent re-triggering (if filesystem is writable)
        if [[ -f "${DONE_FILE}" ]]; then
            if mv "${DONE_FILE}" "${DONE_FILE}.processed.$(date +%s)" 2>/dev/null; then
                log_debug "Moved done file to prevent re-processing"
            else
                log_debug "Cannot move done file (read-only filesystem), will track by timestamp"
            fi
        fi
    else
        local exit_code=$?
        log_error "Repository update failed with exit code $exit_code"
        return $exit_code
    fi
}

# Function to setup monitoring
setup_monitoring() {
    log_info "Starting done file monitoring for ${REPO_DIR}"
    log_info "Done file: ${DONE_FILE}"
    log_info "Check interval: ${CHECK_INTERVAL}s"
    log_debug "Map file: ${MAP_FILE}"
    log_debug "Setup script: ${SETUP_SCRIPT}"
    
    # Verify the repository directory exists
    if [[ ! -d "${REPO_DIR}" ]]; then
        log_error "Repository directory ${REPO_DIR} does not exist"
        exit 1
    fi
    
    # Initial repository setup if done file already exists
    if [[ -f "${DONE_FILE}" ]]; then
        log_info "Found existing done file, performing initial repository setup..."
        LAST_DONE_TIMESTAMP=$(get_file_timestamp "${DONE_FILE}")
        if ! trigger_update "INITIAL_DONE_FILE_FOUND"; then
            log_warn "Initial repository setup failed, but continuing monitoring..."
        fi
    else
        log_info "No done file found, waiting for build completion..."
        # Still do initial setup if map file exists
        if [[ -f "${MAP_FILE}" ]]; then
            log_info "Map file exists, performing initial repository setup..."
            if ! trigger_update "INITIAL_MAP_FILE_FOUND"; then
                log_warn "Initial repository setup failed, but continuing monitoring..."
            fi
        else
            log_info "No map file found, waiting for build to complete and create files..."
        fi
    fi
}

# Function to check for done file changes
check_done_file() {
    if [[ -f "${DONE_FILE}" ]]; then
        local current_timestamp
        current_timestamp=$(get_file_timestamp "${DONE_FILE}")
        
        # Check if this is a new or updated done file
        if [[ "$current_timestamp" != "$LAST_DONE_TIMESTAMP" ]]; then
            log_info "Build completion detected (timestamp: $current_timestamp)"
            
            # Read the content of the done file for additional info
            if [[ -r "${DONE_FILE}" ]]; then
                local done_content
                done_content=$(cat "${DONE_FILE}")
                log_info "Build completion info: ${done_content}"
            fi
            
            LAST_DONE_TIMESTAMP="$current_timestamp"
            trigger_update "BUILD_COMPLETED"
        else
            log_debug "Done file exists but timestamp unchanged"
        fi
    else
        # Reset timestamp if file was removed
        if [[ -n "$LAST_DONE_TIMESTAMP" ]]; then
            log_debug "Done file removed, resetting timestamp"
            LAST_DONE_TIMESTAMP=""
        fi
    fi
}

# Function to monitor for done file
monitor_done_file() {
    log_info "Monitoring for build completion..."
    
    while true; do
        check_done_file
        sleep "$CHECK_INTERVAL"
    done
}

# Alternative inotify-based monitoring (more efficient)
monitor_done_file_inotify() {
    log_info "Starting inotify-based monitoring for ${DONE_FILE}..."
    
    # Check if inotifywait is available
    if ! command -v inotifywait >/dev/null 2>&1; then
        log_warn "inotifywait not available, falling back to polling"
        monitor_done_file
        return
    fi
    
    # Monitor the repository directory for done file changes
    inotifywait -m -e create,modify,moved_to \
        --format '%f %e %T' --timefmt '%Y-%m-%d %H:%M:%S' \
        "${REPO_DIR}" 2>/dev/null | \
    while read filename event timestamp; do
        if [[ "$filename" == "avocado-build.done" ]]; then
            log_info "Build completion detected via inotify: ${event} at ${timestamp}"
            
            # Small delay to ensure file write is complete
            sleep 1
            
            # Read the content of the done file
            if [[ -f "${DONE_FILE}" && -r "${DONE_FILE}" ]]; then
                local done_content
                done_content=$(cat "${DONE_FILE}")
                log_info "Build completion info: ${done_content}"
            fi
            
            trigger_update "BUILD_COMPLETED_INOTIFY"
        fi
    done
}

# Signal handlers for graceful shutdown
cleanup() {
    # Prevent multiple cleanup calls
    if [ "$CLEANUP_CALLED" = "true" ]; then
        return
    fi
    CLEANUP_CALLED=true
    
    log_info "Received shutdown signal, cleaning up..."
    
    # Kill any background processes (like inotifywait)
    local jobs_list
    jobs_list=$(jobs -p 2>/dev/null || true)
    if [ -n "$jobs_list" ]; then
        echo "$jobs_list" | xargs -r kill -TERM 2>/dev/null || true
        sleep 1
        # Force kill any remaining processes
        echo "$jobs_list" | xargs -r kill -KILL 2>/dev/null || true
    fi
    
    log_info "Done file monitor stopped"
    exit 0
}

trap cleanup SIGTERM SIGINT

# Main execution
main() {
    setup_monitoring
    
    # Use inotify if available, otherwise fall back to polling
    if command -v inotifywait >/dev/null 2>&1; then
        monitor_done_file_inotify
    else
        monitor_done_file
    fi
}

# Run main function
main "$@"
