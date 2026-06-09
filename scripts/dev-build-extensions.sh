#!/usr/bin/env bash

set -e # Exit immediately if a command exits with a non-zero status.

# Default configuration
DEFAULT_REPO_DIR="/tmp/avocado-dev-repo"
DEFAULT_DISTRO_CODENAME="2026/edge"
DEFAULT_CONTAINER_NAME="avocado-dev-repo"
DEFAULT_NETWORK_NAME="avocado-dev-network"
DEFAULT_REPO_URL="http://$DEFAULT_CONTAINER_NAME"
DEFAULT_RELEASE_DIR=""  # Empty means auto-detect latest
DEFAULT_SKIP_CLEANUP=false
DEFAULT_SKIP_PACKAGE=false

# Function to show usage
usage() {
    cat << EOF
Usage: $0 [OPTIONS] -t <target> [extension1] [extension2] ...

Build extensions for a specific target using the development repository.

Required:
    -t, --target TARGET     Target name (e.g., qemux86-64, raspberrypi4)

Options:
    -r, --repo-dir DIR      Repository directory (default: $DEFAULT_REPO_DIR)
    -d, --distro CODENAME   Distribution codename (default: $DEFAULT_DISTRO_CODENAME)
    -u, --repo-url URL      Repository URL (default: http://<container-name>)
    -n, --container-name NAME   Repository container name (default: $DEFAULT_CONTAINER_NAME)
    --network NETWORK       Docker network name (default: $DEFAULT_NETWORK_NAME)
    --release-dir DIR       Specific release directory name (default: auto-detect latest)
    -E, --extensions-dir DIR    Top-level directory holding ALL extensions as
                                <type>-<name> subdirs (e.g. bsp-qemuarm64, ext-dev),
                                instead of the in-repo extensions/ + bsp/ split.
                                Defaults to \$AVOCADO_EXTENSIONS_DIR if set.
    --skip-cleanup          Skip cleaning up extension build artifacts after building
    --skip-package          Skip packaging extensions after building
    --all                   Build all extensions that support the target
    --list                  List available extensions and their supported targets
    -h, --help              Show this help message

Examples:
    $0 -t qemux86-64 --all                     # Build all extensions for qemux86-64
    $0 -t raspberrypi4 docker sshd             # Build specific extensions
    $0 -t raspberrypi4 bsp-raspberrypi4        # Build BSP extension for raspberrypi4
    $0 --list                                   # List all extensions
    $0 -t qemux86-64 -u http://my-repo-container dev   # Use custom repo container
    $0 -t qemux86-64 --all --skip-cleanup      # Build all extensions but skip cleanup
    $0 -t qemux86-64 --all --skip-package      # Build only, skip packaging

This script:
1. Checks that the repository server is running
2. Discovers available extensions (both regular and BSP) and their supported targets
3. Builds the specified extensions for the target using 'avocado build'
4. Calls dev-package-extensions.sh to package and deploy (unless --skip-package)

EOF
}

# Function to find the latest release directory
find_latest_release_dir() {
    local releases_base_dir="$REPO_DIR/releases/$DISTRO_CODENAME"
    
    if [ ! -d "$releases_base_dir" ]; then
        echo "Error: Releases directory not found: $releases_base_dir" >&2
        return 1
    fi
    
    # Find the latest timestamped directory (dev-YYYYMMDD-HHMMSS format)
    local latest_dir=$(find "$releases_base_dir" -maxdepth 1 -type d -name "dev-*" | sort -V | tail -n 1)
    
    if [ -z "$latest_dir" ]; then
        echo "Error: No release directories found in $releases_base_dir" >&2
        echo "Expected directories with format: dev-YYYYMMDD-HHMMSS" >&2
        return 1
    fi
    
    echo "$(basename "$latest_dir")"
}

# Function to check if avocado CLI is available
check_avocado_cli() {
    if ! command -v avocado &> /dev/null; then
        echo "Error: avocado CLI not found" >&2
        echo "Please install avocado CLI first:" >&2
        echo "  curl -fsSL https://github.com/avocadolinux/avocado/releases/latest/download/avocado-linux-amd64 -o /usr/local/bin/avocado" >&2
        echo "  chmod +x /usr/local/bin/avocado" >&2
        exit 1
    fi
}

# Function to check if repository server is running
check_repo_server() {
    if ! docker ps --filter "name=^${CONTAINER_NAME}$" --filter "status=running" --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
        echo "Error: Repository server container '$CONTAINER_NAME' is not running" >&2
        echo "Start it first with: ./scripts/dev-start-repo.sh -r '$REPO_DIR'" >&2
        exit 1
    fi
    
    # Test if the repository is accessible via localhost port mapping
    # (The avocado CLI will use the container name, but we test via localhost)
    LOCAL_REPO_URL="http://localhost:8080"
    if ! curl -s --connect-timeout 5 "$LOCAL_REPO_URL" > /dev/null; then
        echo "Error: Repository server is not accessible via $LOCAL_REPO_URL" >&2
        echo "Check that the container is running and port 8080 is mapped" >&2
        echo "The avocado CLI will connect to: $REPO_URL" >&2
        exit 1
    fi
    
    echo "✓ Repository server is accessible (avocado CLI will use: $REPO_URL)"
}

# Function to parse YAML supported_targets field (handles both inline and multi-line list formats)
parse_yaml_supported_targets() {
    local yaml_file="$1"
    local supported_targets=""
    
    if ! grep -q '^supported_targets:' "$yaml_file"; then
        # Field not present, default to all targets
        echo "*"
        return
    fi
    
    # First, try to get inline value (e.g., "supported_targets: '*'" or "supported_targets: [a, b]")
    local inline_value=$(grep '^supported_targets:' "$yaml_file" | sed 's/supported_targets: *//' | tr -d '"' | tr -d "'" | tr -d ' ')
    
    if [ -n "$inline_value" ]; then
        # Inline format found
        echo "$inline_value"
        return
    fi
    
    # Multi-line YAML list format - extract items following "supported_targets:"
    # Use awk to find lines starting with "- " (possibly indented) after "supported_targets:" until next non-list line
    local targets=$(awk '
        /^supported_targets:/ { in_list=1; next }
        in_list && /^[^ \t-]/ { exit }
        in_list && /^[ \t]*- / { gsub(/^[ \t]*- /, ""); gsub(/["\047]/, ""); printf "%s,", $0 }
    ' "$yaml_file" | sed 's/,$//')
    
    if [ -n "$targets" ]; then
        echo "$targets"
    else
        # No targets found, default to all
        echo "*"
    fi
}

# Function to discover extensions and their supported targets
# Resolve an extension identifier to its source dir and package name, setting the
# `ext_dir` and `package_name` variables in the caller's scope. See the matching
# helper in dev-package-extensions.sh for the layout rules.
resolve_extension_paths() {
    local extension="$1"
    if [ -n "$EXTENSIONS_DIR" ]; then
        ext_dir="$EXTENSIONS_DIR/$extension"
        package_name="avocado-$extension"
    elif [[ "$extension" == bsp-* ]]; then
        ext_dir="bsp/${extension#bsp-}"
        package_name="avocado-bsp-${extension#bsp-}"
    else
        ext_dir="extensions/$extension"
        package_name="avocado-ext-$extension"
    fi
}

discover_extensions() {
    local extensions_info=()

    if [ -n "$EXTENSIONS_DIR" ]; then
        # Combined mode: all extensions are <type>-<name> subdirs of one dir.
        local ext_dir
        for ext_dir in "$EXTENSIONS_DIR"/*/; do
            if [ -d "$ext_dir" ] && [ -f "$ext_dir/avocado.yaml" ]; then
                local extension=$(basename "$ext_dir")
                local supported_targets=$(parse_yaml_supported_targets "$ext_dir/avocado.yaml")
                extensions_info+=("$extension:$supported_targets")
            fi
        done
        printf '%s\n' "${extensions_info[@]}"
        return
    fi

    # Legacy in-repo layout: regular extensions under extensions/, BSPs under bsp/.
    for ext_dir in extensions/*/; do
        if [ -d "$ext_dir" ] && [ -f "$ext_dir/avocado.yaml" ]; then
            local extension=$(basename "$ext_dir")
            local supported_targets=$(parse_yaml_supported_targets "$ext_dir/avocado.yaml")
            extensions_info+=("$extension:$supported_targets")
        fi
    done

    # Discover BSP extensions
    for bsp_dir in bsp/*/; do
        if [ -d "$bsp_dir" ] && [ -f "$bsp_dir/avocado.yaml" ]; then
            local bsp_name=$(basename "$bsp_dir")
            local extension="bsp-$bsp_name"
            local supported_targets=$(parse_yaml_supported_targets "$bsp_dir/avocado.yaml")
            extensions_info+=("$extension:$supported_targets")
        fi
    done

    printf '%s\n' "${extensions_info[@]}"
}

# Function to list extensions
list_extensions() {
    echo "Available extensions and their supported targets:"
    echo ""
    
    # Separate regular and BSP extensions for better display
    local regular_extensions=()
    local bsp_extensions=()
    
    while IFS=':' read -r extension supported_targets; do
        if [[ "$extension" == bsp-* ]]; then
            bsp_extensions+=("$extension:$supported_targets")
        else
            regular_extensions+=("$extension:$supported_targets")
        fi
    done < <(discover_extensions)
    
    # Display regular extensions
    if [ ${#regular_extensions[@]} -gt 0 ]; then
        echo "Regular Extensions:"
        for ext_info in "${regular_extensions[@]}"; do
            IFS=':' read -r extension supported_targets <<< "$ext_info"
            printf "  %-20s %s\n" "$extension" "$supported_targets"
        done
        echo ""
    fi
    
    # Display BSP extensions
    if [ ${#bsp_extensions[@]} -gt 0 ]; then
        echo "BSP Extensions:"
        for ext_info in "${bsp_extensions[@]}"; do
            IFS=':' read -r extension supported_targets <<< "$ext_info"
            printf "  %-20s %s\n" "$extension" "$supported_targets"
        done
    fi
}

# Function to check if extension supports target
extension_supports_target() {
    local extension="$1"
    local target="$2"
    local supported_targets="$3"
    
    if [ "$supported_targets" = "*" ]; then
        return 0
    fi
    
    # Parse comma-separated targets or inline array format: [target1, target2]
    local targets_list=$(echo "$supported_targets" | sed 's/\[//g' | sed 's/\]//g' | sed 's/"//g' | sed "s/'//g" | tr ',' '\n')
    
    for supported_target in $targets_list; do
        supported_target=$(echo "$supported_target" | xargs) # trim whitespace
        if [ "$supported_target" = "$target" ]; then
            return 0
        fi
    done
    
    return 1
}

# Function to get extensions for target
get_extensions_for_target() {
    local target="$1"
    local extensions=()
    
    while IFS=':' read -r extension supported_targets; do
        if extension_supports_target "$extension" "$target" "$supported_targets"; then
            extensions+=("$extension")
        fi
    done < <(discover_extensions)
    
    printf '%s\n' "${extensions[@]}"
}

# Function to build extension
build_extension() {
    local extension="$1"
    local target="$2"
    
    echo "Building extension: $extension for target: $target"
    
    # Determine extension directory and package name (combined or legacy layout)
    local ext_dir=""
    local package_name=""
    resolve_extension_paths "$extension"

    if [ ! -d "$ext_dir" ]; then
        echo "Error: Extension directory '$ext_dir' not found" >&2
        return 1
    fi
    
    if [ ! -f "$ext_dir/avocado.yaml" ]; then
        echo "Error: Extension configuration '$ext_dir/avocado.yaml' not found" >&2
        return 1
    fi
    
    # Change to extension directory
    cd "$ext_dir"
    
    # Parse src_dir from avocado.yaml and remove .avocado folder from there
    local src_dir=$(grep '^src_dir:' avocado.yaml | sed 's/src_dir: *//' | tr -d '"' | tr -d "'" | xargs)
    if [ -z "$src_dir" ]; then
        src_dir="."
    fi
    local avocado_dir="$src_dir/.avocado"
    if [ -d "$avocado_dir" ]; then
        echo "  Removing .avocado folder from $avocado_dir..."
        rm -rf "$avocado_dir"
    fi
    
    # Set up environment for avocado CLI
    export AVOCADO_SDK_REPO_URL="$REPO_URL"
    export AVOCADO_CONTAINER_NETWORK="$NETWORK_NAME"
    export AVOCADO_SDK_REPO_RELEASE="$DISTRO_CODENAME"
    # The extension's avocado.yaml selects its SDK image as
    # avocadolinux/sdk:${AVOCADO_DISTRO_RELEASE}-${AVOCADO_DISTRO_CHANNEL}. Derive
    # both from the distro codename (release/channel) so the tag matches the
    # locally built/loaded SDK (e.g. 2026/edge -> sdk:2026-edge). Honor values
    # already exported by the caller.
    export AVOCADO_DISTRO_RELEASE="${AVOCADO_DISTRO_RELEASE:-${DISTRO_CODENAME%%/*}}"
    export AVOCADO_DISTRO_CHANNEL="${AVOCADO_DISTRO_CHANNEL:-${DISTRO_CODENAME##*/}}"

    echo "  Cleaning extension environment before build..."
    if ! avocado ext clean -e "$package_name" --target "$target"; then
        echo "  ⚠ Extension clean had issues, continuing..."
    fi
    
    echo "  Building extension with avocado build..."
    if ! avocado build -e "$package_name" --target "$target" --container-arg "--network" --container-arg "$NETWORK_NAME"; then
        echo "  ✗ Failed to build extension" >&2
        cd - > /dev/null
        return 1
    fi
    
    # Return to original directory
    cd - > /dev/null
    
    echo "  ✓ Extension $extension built successfully for $target"
}

# Parse command line arguments
REPO_DIR="$DEFAULT_REPO_DIR"
DISTRO_CODENAME="$DEFAULT_DISTRO_CODENAME"
REPO_URL="$DEFAULT_REPO_URL"
CONTAINER_NAME="$DEFAULT_CONTAINER_NAME"
NETWORK_NAME="$DEFAULT_NETWORK_NAME"
RELEASE_DIR="$DEFAULT_RELEASE_DIR"
SKIP_CLEANUP="$DEFAULT_SKIP_CLEANUP"
SKIP_PACKAGE="$DEFAULT_SKIP_PACKAGE"
TARGET=""
EXTENSIONS=()
BUILD_ALL=false
LIST_ONLY=false
# Combined extensions dir (all extensions as <type>-<name> subdirs). Empty = legacy
# in-repo extensions/ + bsp/ layout. Env var provides a default for the eventual
# move of these scripts out of avocado-os.
EXTENSIONS_DIR="${AVOCADO_EXTENSIONS_DIR:-}"

while [[ $# -gt 0 ]]; do
    case $1 in
        -t|--target)
            TARGET="$2"
            shift 2
            ;;
        -E|--extensions-dir)
            EXTENSIONS_DIR="$2"
            shift 2
            ;;
        -r|--repo-dir)
            REPO_DIR="$2"
            shift 2
            ;;
        -d|--distro)
            DISTRO_CODENAME="$2"
            shift 2
            ;;
        -u|--repo-url)
            REPO_URL="$2"
            shift 2
            ;;
        -n|--container-name)
            CONTAINER_NAME="$2"
            shift 2
            ;;
        --network)
            NETWORK_NAME="$2"
            shift 2
            ;;
        --release-dir)
            RELEASE_DIR="$2"
            shift 2
            ;;
        --skip-cleanup)
            SKIP_CLEANUP=true
            shift
            ;;
        --skip-package)
            SKIP_PACKAGE=true
            shift
            ;;
        --all)
            BUILD_ALL=true
            shift
            ;;
        --list)
            LIST_ONLY=true
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
            EXTENSIONS+=("$1")
            shift
            ;;
    esac
done

# Convert relative path to absolute path
REPO_DIR="$(realpath "$REPO_DIR")"

# Resolve the combined extensions dir to an absolute path so resolution works
# regardless of the current working directory, and so it can be passed through to
# dev-package-extensions.sh unambiguously.
if [ -n "$EXTENSIONS_DIR" ]; then
    if [ ! -d "$EXTENSIONS_DIR" ]; then
        echo "Error: extensions dir '$EXTENSIONS_DIR' not found" >&2
        exit 1
    fi
    EXTENSIONS_DIR="$(realpath "$EXTENSIONS_DIR")"
    echo "Using combined extensions directory: $EXTENSIONS_DIR"
fi

echo "=== Avocado Development Extension Builder ==="

# Handle list-only mode
if [ "$LIST_ONLY" = true ]; then
    list_extensions
    exit 0
fi

# Validate required arguments
if [ -z "$TARGET" ]; then
    echo "Error: Target is required (use -t/--target)" >&2
    usage >&2
    exit 1
fi

# Check prerequisites
check_avocado_cli
check_repo_server

# Determine release directory
if [ -z "$RELEASE_DIR" ]; then
    echo "Auto-detecting latest release directory..."
    RELEASE_DIR=$(find_latest_release_dir)
    if [ $? -ne 0 ]; then
        exit 1
    fi
    echo "Using latest release directory: $RELEASE_DIR"
else
    echo "Using specified release directory: $RELEASE_DIR"
    # Validate that the specified release directory exists
    if [ ! -d "$REPO_DIR/releases/$DISTRO_CODENAME/$RELEASE_DIR" ]; then
        echo "Error: Specified release directory does not exist: $REPO_DIR/releases/$DISTRO_CODENAME/$RELEASE_DIR" >&2
        exit 1
    fi
fi

echo "Target: $TARGET"
echo "Repository directory: $REPO_DIR"
echo "Distribution codename: $DISTRO_CODENAME"
echo "Release directory: $RELEASE_DIR"
echo "Container name: $CONTAINER_NAME"
echo "Network name: $NETWORK_NAME"
echo "Skip cleanup: $SKIP_CLEANUP"
echo "Skip package: $SKIP_PACKAGE"
echo ""
echo "Docker networking configuration:"
echo "  Repository URL (for avocado CLI): $REPO_URL"
echo "  Avocado containers will connect via Docker network: $NETWORK_NAME"
echo "  All avocado commands will use --container-arg --network --container-arg $NETWORK_NAME"
echo ""

# Determine which extensions to build
if [ "$BUILD_ALL" = true ]; then
    echo "Building all extensions that support target: $TARGET"
    mapfile -t EXTENSIONS < <(get_extensions_for_target "$TARGET")
    
    if [ ${#EXTENSIONS[@]} -eq 0 ]; then
        echo "No extensions support target: $TARGET"
        exit 0
    fi
    
    echo "Extensions to build: ${EXTENSIONS[*]}"
elif [ ${#EXTENSIONS[@]} -eq 0 ]; then
    echo "Error: No extensions specified. Use --all or specify extension names" >&2
    usage >&2
    exit 1
fi

echo ""

# Validate that specified extensions support the target
if [ "$BUILD_ALL" = false ]; then
    echo "Validating extensions support target: $TARGET"
    for extension in "${EXTENSIONS[@]}"; do
        extension_info=""
        while IFS=':' read -r ext_name supported_targets; do
            if [ "$ext_name" = "$extension" ]; then
                extension_info="$supported_targets"
                break
            fi
        done < <(discover_extensions)
        
        if [ -z "$extension_info" ]; then
            echo "Error: Extension '$extension' not found" >&2
            exit 1
        fi
        
        if ! extension_supports_target "$extension" "$TARGET" "$extension_info"; then
            echo "Error: Extension '$extension' does not support target '$TARGET'" >&2
            echo "Supported targets: $extension_info" >&2
            exit 1
        fi
        
        echo "  ✓ $extension supports $TARGET"
    done
    echo ""
fi

# Build extensions
echo "Building ${#EXTENSIONS[@]} extension(s)..."
failed_extensions=()
built_extensions=()

for extension in "${EXTENSIONS[@]}"; do
    echo ""
    echo "--- Building $extension ---"
    if build_extension "$extension" "$TARGET"; then
        built_extensions+=("$extension")
        echo "✓ Successfully built extension: $extension"
    else
        echo "✗ Failed to build extension: $extension"
        echo "Stopping build due to failure."
        exit 1
    fi
done

echo ""
echo "=== Build Complete ==="
echo "✓ All ${#EXTENSIONS[@]} extension(s) built successfully"

# Call packaging script unless skipped
if [ "$SKIP_PACKAGE" = false ]; then
    echo ""
    echo "=== Packaging Extensions ==="
    
    # Build the arguments for the packaging script
    PACKAGE_ARGS=(
        --target "$TARGET"
        --repo-dir "$REPO_DIR"
        --distro "$DISTRO_CODENAME"
        --repo-url "$REPO_URL"
        --container-name "$CONTAINER_NAME"
        --network "$NETWORK_NAME"
        --release-dir "$RELEASE_DIR"
    )

    # Forward the combined extensions dir so packaging resolves the same dirs.
    if [ -n "$EXTENSIONS_DIR" ]; then
        PACKAGE_ARGS+=(--extensions-dir "$EXTENSIONS_DIR")
    fi

    if [ "$SKIP_CLEANUP" = true ]; then
        PACKAGE_ARGS+=(--skip-cleanup)
    fi
    
    # Pass the extensions to package
    PACKAGE_ARGS+=("${built_extensions[@]}")
    
    # Get the directory of this script to find the packaging script
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    
    "$SCRIPT_DIR/dev-package-extensions.sh" "${PACKAGE_ARGS[@]}"
    
    if [ $? -eq 0 ]; then
        echo "✓ Packaging completed successfully"
    else
        echo "✗ Packaging failed"
        exit 1
    fi
else
    echo ""
    echo "Skipping packaging (--skip-package was specified)"
    echo "To package extensions later, run:"
    echo "  ./scripts/dev-package-extensions.sh -t $TARGET ${built_extensions[*]}"
fi

echo ""
echo "Extension packages available at:"
echo "  Extension packages: $REPO_DIR/packages/$DISTRO_CODENAME/target/$TARGET-ext/"
echo "  Extension releases: $REPO_DIR/releases/$DISTRO_CODENAME/$RELEASE_DIR/target/$TARGET-ext/"
echo "  SDK packages: $REPO_DIR/packages/$DISTRO_CODENAME/sdk/$TARGET/"
echo "  SDK releases: $REPO_DIR/releases/$DISTRO_CODENAME/$RELEASE_DIR/sdk/$TARGET/"
echo "  targets.json: $REPO_DIR/releases/$DISTRO_CODENAME/$RELEASE_DIR/targets.json"
echo "Repository URL: $REPO_URL/"
