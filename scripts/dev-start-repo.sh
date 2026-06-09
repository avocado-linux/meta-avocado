#!/usr/bin/env bash

set -e # Exit immediately if a command exits with a non-zero status.

# Directory of this script and the repo root, so the local repo-server image
# context resolves regardless of the caller's working directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCAL_REPO_IMAGE_DIR="$REPO_ROOT/support/package-repo-local"
# Distinct tag for the lightweight dev server (nginx:alpine, root /avocado-repo).
# Deliberately NOT package-repo:local — that tag is used elsewhere for the
# production server (fedora, root /var/www/html); sharing it served the wrong image.
LOCAL_REPO_IMAGE="avocadolinux/package-repo:dev-local"

# Default configuration
DEFAULT_REPO_DIR="/tmp/avocado-dev-repo"
DEFAULT_PORT="8080"
DEFAULT_CONTAINER_NAME="avocado-dev-repo"
DEFAULT_NETWORK_NAME="avocado-dev-network"
DEFAULT_DISTRO_CODENAME="2026/edge"
DEFAULT_USER_ID="$(id -u)"
DEFAULT_GROUP_ID="$(id -g)"

# Function to show usage
usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Start a development package repository server using Docker.

Options:
    -r, --repo-dir DIR      Repository directory (default: $DEFAULT_REPO_DIR)
    -p, --port PORT         Host port to bind to (default: $DEFAULT_PORT)
    -n, --name NAME         Container name (default: $DEFAULT_CONTAINER_NAME)
    --network NETWORK       Docker network name (default: $DEFAULT_NETWORK_NAME)
    -d, --distro CODENAME   Distribution codename (default: $DEFAULT_DISTRO_CODENAME)
    -i, --release-id ID     Release id under the codename to serve as latest
                            (default: most recently modified release dir)
    --user-id UID           User ID for container (default: current user ID)
    --group-id GID          Group ID for container (default: current group ID)
    --stop                  Stop the running repository server
    --restart               Restart the repository server
    --logs                  Show container logs
    --status                Show container status
    --env                   Export environment variables to .avocado-dev-env
    -h, --help              Show this help message

Examples:
    $0                                          # Start with defaults
    $0 -r /opt/avocado-repo -p 9000            # Custom repo dir and port
    $0 -d "2026/edge"                             # Custom distro codename
    $0 --user-id 1000 --group-id 1000          # Custom user/group IDs
    $0 --stop                                   # Stop the server
    $0 --restart                               # Restart the server
    $0 --logs                                   # View logs
    $0 --status                                 # Check status
    $0 --env                                    # Export env vars to .avocado-dev-env

The repository server will serve packages from the specified directory and
automatically update metadata when packages are added or changed.

Repository structure expected (production-style):
    <repo-dir>/
    ├── packages/<distro-codename>/     # Package files
    └── releases/<distro-codename>/     # Repository metadata with timestamped subdirs

The server will be accessible at http://localhost:<port>/
- Packages: http://localhost:<port>/packages/
- Releases: http://localhost:<port>/releases/
- Latest: http://localhost:<port>/<distro-codename>/ (points to most recent release)

EOF
}

# Function to check if container exists
container_exists() {
    docker ps -a --filter "name=^${CONTAINER_NAME}$" --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"
}

# Function to check if container is running
container_running() {
    docker ps --filter "name=^${CONTAINER_NAME}$" --filter "status=running" --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"
}

# Function to check if network exists
network_exists() {
    docker network ls --filter "name=^${NETWORK_NAME}$" --format "{{.Name}}" | grep -q "^${NETWORK_NAME}$"
}

# Function to create network if it doesn't exist
ensure_network() {
    if ! network_exists; then
        echo "Creating Docker network: $NETWORK_NAME"
        docker network create "$NETWORK_NAME"
    else
        echo "Using existing Docker network: $NETWORK_NAME"
    fi
}

# Function to build the package-repo image if it doesn't exist
ensure_image() {
    if ! docker images --format "{{.Repository}}:{{.Tag}}" | grep -q "^${LOCAL_REPO_IMAGE}$"; then
        echo "Building package-repo Docker image ($LOCAL_REPO_IMAGE)..."
        docker build -f "$LOCAL_REPO_IMAGE_DIR/Containerfile-local" -t "$LOCAL_REPO_IMAGE" "$LOCAL_REPO_IMAGE_DIR"
    else
        echo "Using existing package-repo Docker image"
    fi
}

# Function to stop container
stop_container() {
    if container_running; then
        echo "Stopping container: $CONTAINER_NAME"
        docker stop "$CONTAINER_NAME"
    fi
    
    if container_exists; then
        echo "Removing container: $CONTAINER_NAME"
        docker rm "$CONTAINER_NAME"
    fi
}

# Function to start container
start_container() {
    # Validate repository directory
    if [ ! -d "$REPO_DIR" ]; then
        echo "Error: Repository directory '$REPO_DIR' not found" >&2
        echo "Create it first or use dev-sync-packages.sh to populate it." >&2
        exit 1
    fi
    
    # Set up directory paths
    PACKAGES_PATH="$REPO_DIR/packages"
    RELEASES_PATH="$REPO_DIR/releases"
    
    # Create required directory structure if it doesn't exist
    mkdir -p "$PACKAGES_PATH"
    mkdir -p "$RELEASES_PATH"
    
    # Find the most recent release directory for the distro codename
    DISTRO_RELEASES_PATH="$RELEASES_PATH/$DISTRO_CODENAME"
    
    if [ -n "$RELEASE_ID" ] && [ -d "$DISTRO_RELEASES_PATH/$RELEASE_ID" ]; then
        # Explicit release id requested: mount exactly that release as latest.
        LATEST_MOUNT_PATH="$DISTRO_RELEASES_PATH/$RELEASE_ID"
        echo "Mounting requested release: $DISTRO_CODENAME/$RELEASE_ID"
    elif [ -n "$RELEASE_ID" ]; then
        echo "Warning: requested release '$DISTRO_CODENAME/$RELEASE_ID' not found, falling back to most recent"
        RELEASE_ID=""
    fi

    if [ -z "${LATEST_MOUNT_PATH:-}" ]; then
        if [ -d "$DISTRO_RELEASES_PATH" ]; then
            # Find the most recently modified directory
            LATEST_DIR=$(find "$DISTRO_RELEASES_PATH" -maxdepth 1 -type d -not -path "$DISTRO_RELEASES_PATH" -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)
            if [ -n "$LATEST_DIR" ] && [ -d "$LATEST_DIR" ]; then
                LATEST_MOUNT_PATH="$LATEST_DIR"
                echo "Found most recent release: $(basename "$LATEST_DIR")"
            else
                echo "No release subdirs found, will mount releases root"
                LATEST_MOUNT_PATH="$RELEASES_PATH"
            fi
        else
            echo "No releases found for $DISTRO_CODENAME, will mount releases root"
            LATEST_MOUNT_PATH="$RELEASES_PATH"
        fi
    fi
    
    # Ensure network and image exist
    ensure_network
    ensure_image
    
    # Stop existing container if running
    if container_running; then
        echo "Container $CONTAINER_NAME is already running"
        echo "Use --restart to restart it or --stop to stop it"
        return 0
    fi
    
    # Remove existing stopped container
    if container_exists; then
        echo "Removing existing stopped container: $CONTAINER_NAME"
        docker rm "$CONTAINER_NAME"
    fi
    
    echo "Starting package repository server..."
    echo "Repository directory: $REPO_DIR"
    echo "Distro codename: $DISTRO_CODENAME"
    echo "Container name: $CONTAINER_NAME"
    echo "Network: $NETWORK_NAME"
    echo "Port: $PORT"
    echo ""
            echo "Volume mounts (production-style):"
        echo "  Packages: $PACKAGES_PATH -> /avocado-repo/packages"
        echo "  Releases: $RELEASES_PATH -> /avocado-repo/releases"
        if [ "$LATEST_MOUNT_PATH" != "$RELEASES_PATH" ]; then
            echo "  Latest: $LATEST_MOUNT_PATH -> /avocado-repo/$DISTRO_CODENAME"
        else
            echo "  Latest: Will be created by build process at /avocado-repo/$DISTRO_CODENAME"
        fi
    
    # Start the container with production-style volume mounts
    if [ "$LATEST_MOUNT_PATH" != "$RELEASES_PATH" ]; then
        # Mount specific timestamped release as latest
        docker run -d --rm \
            --name "$CONTAINER_NAME" \
            --network "$NETWORK_NAME" \
            -p "$PORT:80" \
            -e USER_ID="$USER_ID" \
            -e GROUP_ID="$GROUP_ID" \
            -v "$PACKAGES_PATH:/avocado-repo/packages" \
            -v "$RELEASES_PATH:/avocado-repo/releases" \
            -v "$LATEST_MOUNT_PATH:/avocado-repo/$DISTRO_CODENAME" \
            "$LOCAL_REPO_IMAGE"
    else
        # No specific release found, let build process create structure
        docker run -d --rm \
            --name "$CONTAINER_NAME" \
            --network "$NETWORK_NAME" \
            -p "$PORT:80" \
            -e USER_ID="$USER_ID" \
            -e GROUP_ID="$GROUP_ID" \
            -v "$PACKAGES_PATH:/avocado-repo/packages" \
            -v "$RELEASES_PATH:/avocado-repo/releases" \
            "$LOCAL_REPO_IMAGE"
    fi
    
    echo "✓ Container started successfully"
    
    # Wait for nginx to start
    echo "Waiting for nginx to start..."
    sleep 3
    
    # Verify container is still running
    if ! container_running; then
        echo "✗ Container failed to start or exited unexpectedly" >&2
        echo "Container logs:" >&2
        docker logs "$CONTAINER_NAME" >&2
        exit 1
    fi
    
    echo "✓ Package repository server is running"
    echo ""
    echo "Repository URLs:"
    echo "  Root: http://localhost:$PORT/"
    echo "  Packages: http://localhost:$PORT/packages/"
    echo "  Releases: http://localhost:$PORT/releases/"
    echo "  Latest ($DISTRO_CODENAME): http://localhost:$PORT/$DISTRO_CODENAME/"
    echo ""
    echo "Container name: $CONTAINER_NAME"
    echo "Network name: $NETWORK_NAME"
    echo ""
    echo "Environment variables for avocado CLI:"
    echo "  export AVOCADO_SDK_REPO_URL=\"http://$CONTAINER_NAME\""
    echo "  export AVOCADO_CONTAINER_NETWORK=\"$NETWORK_NAME\""
    echo "  export AVOCADO_SDK_REPO_RELEASE=\"$DISTRO_CODENAME\""
    echo ""
    echo "⚠ IMPORTANT: Make sure to export these environment variables before running avocado commands!"
    echo "The avocado CLI containers must use the container name ($CONTAINER_NAME) as hostname,"
    echo "NOT localhost:$PORT which is only accessible from the host machine."
    echo ""
    echo "Example avocado commands (with network decoration):"
    echo "  avocado ext install -e avocado-ext-EXTENSION -f --target TARGET --container-arg \"--network\" --container-arg \"$NETWORK_NAME\""
    echo "  avocado ext build -e avocado-ext-EXTENSION --target TARGET --container-arg \"--network\" --container-arg \"$NETWORK_NAME\""
    echo "  avocado ext package -e avocado-ext-EXTENSION --target TARGET --out-dir OUTPUT --container-arg \"--network\" --container-arg \"$NETWORK_NAME\""
    echo ""
    echo "Use 'docker logs $CONTAINER_NAME' to view logs"
    echo "Use '$0 --status' to see this information again"
    echo "Use '$0 --stop' to stop the server"
}

# Function to show container status
show_status() {
    if container_running; then
        echo "✓ Container $CONTAINER_NAME is running"
        docker ps --filter "name=^${CONTAINER_NAME}$" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
        echo ""
        echo "Repository URLs:"
        echo "  Root: http://localhost:$PORT/"
        echo "  Packages: http://localhost:$PORT/packages/"
        echo "  Releases: http://localhost:$PORT/releases/"
        echo "  Latest ($DISTRO_CODENAME): http://localhost:$PORT/$DISTRO_CODENAME/"
        echo ""
        echo "Container name: $CONTAINER_NAME"
        echo "Network name: $NETWORK_NAME"
        echo ""
        echo "Environment variables for avocado CLI:"
        echo "  export AVOCADO_SDK_REPO_URL=\"http://$CONTAINER_NAME\""
        echo "  export AVOCADO_CONTAINER_NETWORK=\"$NETWORK_NAME\""
        echo "  export AVOCADO_SDK_REPO_RELEASE=\"$DISTRO_CODENAME\""
        echo ""
        echo "⚠ IMPORTANT: Make sure to export these environment variables before running avocado commands!"
        echo "The avocado CLI containers must use the container name ($CONTAINER_NAME) as hostname,"
        echo "NOT localhost:$PORT which is only accessible from the host machine."
        echo ""
        echo "Example avocado commands (with network decoration):"
        echo "  avocado ext install -e avocado-ext-EXTENSION -f --target TARGET --container-arg \"--network\" --container-arg \"$NETWORK_NAME\""
        echo "  avocado ext build -e avocado-ext-EXTENSION --target TARGET --container-arg \"--network\" --container-arg \"$NETWORK_NAME\""
        echo "  avocado ext package -e avocado-ext-EXTENSION --target TARGET --out-dir OUTPUT --container-arg \"--network\" --container-arg \"$NETWORK_NAME\""
    elif container_exists; then
        echo "⚠ Container $CONTAINER_NAME exists but is not running"
        docker ps -a --filter "name=^${CONTAINER_NAME}$" --format "table {{.Names}}\t{{.Status}}"
    else
        echo "✗ Container $CONTAINER_NAME does not exist"
    fi
}

# Function to show logs
show_logs() {
    if container_exists; then
        docker logs -f "$CONTAINER_NAME"
    else
        echo "Error: Container $CONTAINER_NAME does not exist" >&2
        exit 1
    fi
}

# Function to export environment variables
export_env() {
    if ! container_running; then
        echo "Error: Container $CONTAINER_NAME is not running" >&2
        echo "Start the container first with: $0" >&2
        exit 1
    fi
    
    ENV_FILE=".avocado-dev-env"
    
    cat > "$ENV_FILE" << EOF
# Avocado Development Environment Variables
# Source this file with: source $ENV_FILE

# CRITICAL: These environment variables configure avocado CLI to use container networking
# The AVOCADO_SDK_REPO_URL MUST use the container name ($CONTAINER_NAME) as hostname,
# NOT localhost:$PORT which is only accessible from the host machine.

export AVOCADO_SDK_REPO_URL="http://$CONTAINER_NAME"
export AVOCADO_CONTAINER_NETWORK="$NETWORK_NAME"
export AVOCADO_SDK_REPO_RELEASE="$DISTRO_CODENAME"

# Helper function for avocado commands with network decoration
avocado_dev() {
    echo "Running: avocado \$@ --container-arg --network --container-arg $NETWORK_NAME"
    echo "Using repo URL: \$AVOCADO_SDK_REPO_URL"
    avocado "\$@" --container-arg "--network" --container-arg "$NETWORK_NAME"
}

echo "✓ Avocado development environment loaded"
echo "Container: $CONTAINER_NAME"
echo "Network: $NETWORK_NAME"
echo "Distro: $DISTRO_CODENAME"
echo "Repo URL: \$AVOCADO_SDK_REPO_URL"
echo ""
echo "⚠ IMPORTANT: Avocado CLI containers will connect to '$CONTAINER_NAME', not localhost"
echo "Use 'avocado_dev' instead of 'avocado' for network-decorated commands"
echo "Example: avocado_dev ext install -e avocado-ext-EXTENSION -f --target TARGET"
EOF
    
    echo "✓ Environment variables exported to $ENV_FILE"
    echo ""
    echo "To use these variables, run:"
    echo "  source $ENV_FILE"
    echo ""
    echo "Then you can use 'avocado_dev' instead of 'avocado' for network-decorated commands"
    echo ""
    echo "To test the connection, try:"
    echo "  curl http://$CONTAINER_NAME/$DISTRO_CODENAME/ --connect-to $CONTAINER_NAME:80:localhost:$PORT"
    echo "  (This simulates how avocado CLI containers will connect)"
}

# Parse command line arguments
REPO_DIR="$DEFAULT_REPO_DIR"
PORT="$DEFAULT_PORT"
CONTAINER_NAME="$DEFAULT_CONTAINER_NAME"
NETWORK_NAME="$DEFAULT_NETWORK_NAME"
DISTRO_CODENAME="$DEFAULT_DISTRO_CODENAME"
RELEASE_ID=""
USER_ID="$DEFAULT_USER_ID"
GROUP_ID="$DEFAULT_GROUP_ID"
ACTION="start"

while [[ $# -gt 0 ]]; do
    case $1 in
        -r|--repo-dir)
            REPO_DIR="$2"
            shift 2
            ;;
        -p|--port)
            PORT="$2"
            shift 2
            ;;
        -n|--name)
            CONTAINER_NAME="$2"
            shift 2
            ;;
        --network)
            NETWORK_NAME="$2"
            shift 2
            ;;
        -d|--distro)
            DISTRO_CODENAME="$2"
            shift 2
            ;;
        -i|--release-id)
            RELEASE_ID="$2"
            shift 2
            ;;
        --user-id)
            USER_ID="$2"
            shift 2
            ;;
        --group-id)
            GROUP_ID="$2"
            shift 2
            ;;
        --stop)
            ACTION="stop"
            shift
            ;;
        --restart)
            ACTION="restart"
            shift
            ;;
        --logs)
            ACTION="logs"
            shift
            ;;
        --status)
            ACTION="status"
            shift
            ;;
        --env)
            ACTION="env"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        -*)
            echo "Error: Unknown option $1" >&2
            usage >&2
            exit 1
            ;;
        *)
            echo "Error: Unexpected argument $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

# Convert relative path to absolute path
REPO_DIR="$(realpath "$REPO_DIR")"

echo "=== Avocado Development Repository Server ==="

case $ACTION in
    start)
        start_container
        ;;
    stop)
        stop_container
        echo "✓ Repository server stopped"
        ;;
    restart)
        stop_container
        start_container
        ;;
    logs)
        show_logs
        ;;
    status)
        show_status
        ;;
    env)
        export_env
        ;;
    *)
        echo "Error: Unknown action $ACTION" >&2
        exit 1
        ;;
esac
