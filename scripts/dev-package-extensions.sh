#!/usr/bin/env bash

set -e # Exit immediately if a command exits with a non-zero status.

# Directory of this script, so sibling repo-*/render helpers resolve regardless of cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Default configuration
DEFAULT_REPO_DIR="/tmp/avocado-dev-repo"
DEFAULT_DISTRO_CODENAME="2026/edge"
DEFAULT_CONTAINER_NAME="avocado-dev-repo"
DEFAULT_NETWORK_NAME=""
DEFAULT_REPO_URL=""
DEFAULT_RELEASE_DIR=""  # Empty means auto-detect latest
DEFAULT_SKIP_CLEANUP=false

# Function to show usage
usage() {
    cat << EOF
Usage: $0 [OPTIONS] -t <target> [extension1] [extension2] ...

Package extensions for a specific target using the development repository.

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
    --skip-cleanup          Skip cleaning up extension build artifacts after packaging
    --all                   Package all extensions that support the target
    --list                  List available extensions and their supported targets
    -h, --help              Show this help message

Examples:
    $0 -t qemux86-64 --all                     # Package all extensions for qemux86-64
    $0 -t raspberrypi4 docker sshd             # Package specific extensions
    $0 -t raspberrypi4 bsp-raspberrypi4        # Package BSP extension for raspberrypi4
    $0 --list                                   # List all extensions
    $0 -t qemux86-64 --all --skip-cleanup      # Package all extensions but skip cleanup
    $0 -t qemuarm64 --all -E /src/avocado-linux/extensions   # Package from a combined extensions dir

This script:
1. Discovers available extensions (both regular and BSP) and their supported targets
2. Packages the specified extensions for the target using 'avocado ext package'
3. Copies built packages to the repository
4. Updates extension repository metadata
5. Generates targets.json from target fragments
6. Cleans up extension build artifacts (unless --skip-cleanup is used)

Note: This script does not require the repository server to be running.

The built extension packages will be available in:
    <repo-dir>/packages/<distro-codename>/target/<target>-ext/

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

# Resolve an extension identifier to its source dir and package name, setting the
# `ext_dir` and `package_name` variables in the caller's scope.
#
# Combined mode (EXTENSIONS_DIR set): every extension is a `<type>-<name>` subdir
# (bsp-<name>, ext-<name>), so the dir IS the identifier and the package is
# avocado-<identifier> — no bsp/ext special-casing.
# Legacy mode: regular extensions live in extensions/<name> (avocado-ext-<name>);
# BSPs in bsp/<name>, surfaced as identifier bsp-<name> (avocado-bsp-<name>).
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

# Function to discover extensions and their supported targets
discover_extensions() {
    local extensions_info=()

    if [ -n "$EXTENSIONS_DIR" ]; then
        # Combined mode: all extensions are <type>-<name> subdirs of one dir; the
        # subdir name is the identifier (already carries the bsp-/ext- prefix).
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

# Function to clean up extension build artifacts
cleanup_extension() {
    local extension="$1"
    local target="$2"
    
    echo "Cleaning up extension: $extension for target: $target"

    # Determine extension directory and package name (combined or legacy layout)
    local ext_dir=""
    local package_name=""
    resolve_extension_paths "$extension"

    if [ ! -d "$ext_dir" ]; then
        echo "  ⚠ Extension directory '$ext_dir' not found, skipping cleanup" >&2
        return 0
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
    
    echo "  Cleaning extension environment..."
    if avocado clean --target "$target" 2>/dev/null; then
        echo "  ✓ Extension $extension cleaned successfully"
    else
        echo "  ⚠ Extension $extension cleanup had issues"
    fi
    
    # Return to original directory
    cd - > /dev/null
}

# Function to package extension
package_extension() {
    local extension="$1"
    local target="$2"
    
    echo "Packaging extension: $extension for target: $target"

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
    
    local output_dir="$extension-$target"
    
    # Clean up any leftover output directory from previous runs
    if [ -d "$output_dir" ]; then
        echo "  Removing leftover output directory: $output_dir"
        rm -rf "$output_dir"
    fi
    
    # Set up environment for avocado CLI
    export AVOCADO_SDK_REPO_RELEASE="$DISTRO_CODENAME"
    # The extension's avocado.yaml selects its SDK image as
    # avocadolinux/sdk:${AVOCADO_DISTRO_RELEASE}-${AVOCADO_DISTRO_CHANNEL}. Derive
    # both from the distro codename (release/channel) so the tag matches the
    # locally built/loaded SDK (e.g. 2026/edge -> sdk:2026-edge). Honor values
    # already exported by the caller.
    export AVOCADO_DISTRO_RELEASE="${AVOCADO_DISTRO_RELEASE:-${DISTRO_CODENAME%%/*}}"
    export AVOCADO_DISTRO_CHANNEL="${AVOCADO_DISTRO_CHANNEL:-${DISTRO_CODENAME##*/}}"
    if [ -n "$REPO_URL" ]; then
        export AVOCADO_SDK_REPO_URL="$REPO_URL"
    fi

    # Build container args for networking
    local container_args=()
    if [ -n "$NETWORK_NAME" ]; then
        container_args+=(--container-arg "--network=$NETWORK_NAME")
    fi

    echo "  Cleaning extension environment before packaging..."
    if ! avocado ext clean -e "$package_name" --target "$target"; then
        echo "  ⚠ Extension clean had issues, continuing..."
    fi

    echo "  Packaging extension with avocado ext package..."
    if ! avocado ext package -e "$package_name" --target "$target" --out-dir "$output_dir" "${container_args[@]}"; then
        echo "  ✗ Failed to package extension" >&2
        cd - > /dev/null
        return 1
    fi
    
    # Copy packages to repository (both packages and releases directories)
    local packages_target_ext_dir="$REPO_DIR/packages/$DISTRO_CODENAME/target/$target-ext"
    local releases_target_ext_dir="$REPO_DIR/releases/$DISTRO_CODENAME/$RELEASE_DIR/target/$target-ext"
    local packages_sdk_dir="$REPO_DIR/packages/$DISTRO_CODENAME/sdk/$target"
    local releases_sdk_dir="$REPO_DIR/releases/$DISTRO_CODENAME/$RELEASE_DIR/sdk/$target"
    
    echo "  Copying packages to repository:"
    echo "    Extension packages: $packages_target_ext_dir"
    echo "    Extension releases: $releases_target_ext_dir"
    echo "    SDK packages: $packages_sdk_dir"
    echo "    SDK releases: $releases_sdk_dir"
    
    mkdir -p "$packages_target_ext_dir"
    mkdir -p "$releases_target_ext_dir"
    mkdir -p "$packages_sdk_dir"
    mkdir -p "$releases_sdk_dir"
    
    if [ -d "$output_dir" ]; then
        local regular_rpm_count=0
        local sdk_rpm_count=0
        
        # Process each RPM package individually to handle all_avocadosdk packages specially
        while IFS= read -r -d '' rpm_file; do
            local rpm_basename=$(basename "$rpm_file")
            
            if [[ "$rpm_basename" == *"all_avocadosdk"* ]]; then
                # Copy all_avocadosdk packages to SDK directories
                cp "$rpm_file" "$packages_sdk_dir/"
                cp "$rpm_file" "$releases_sdk_dir/"
                ((sdk_rpm_count++))
                echo "    SDK: $rpm_basename"
            else
                # Copy regular packages to extension directories
                cp "$rpm_file" "$packages_target_ext_dir/"
                cp "$rpm_file" "$releases_target_ext_dir/"
                ((regular_rpm_count++))
                echo "    EXT: $rpm_basename"
            fi
        done < <(find "$output_dir" -name "*.rpm" -print0)
        
        echo "  ✓ Copied $regular_rpm_count extension packages and $sdk_rpm_count SDK packages"
        
        # Clean up output directory after copying packages
        echo "  Removing output directory: $output_dir"
        rm -rf "$output_dir"
    else
        echo "  ⚠ No output directory found: $output_dir"
    fi
    
    # Return to original directory
    cd - > /dev/null
    
    echo "  ✓ Extension $extension packaged successfully for $target"
}

# Function to update extension metadata
update_extension_metadata() {
    echo "Updating extension repository metadata..."
    echo "Extension metadata will use relative paths to packages"
    
    # Update metadata for both packages and releases directories
    local packages_dir="$REPO_DIR/packages/$DISTRO_CODENAME"
    local releases_dir="$REPO_DIR/releases/$DISTRO_CODENAME/$RELEASE_DIR"
    
    # Render the extension + SDK repos through the SAME content-addressed pool the
    # distro sync uses, so the dev feed mirrors production: packages pooled into
    # <channel-root>/_pkgs, per-repo metadata referencing ../../_pkgs/<aa>/<sha>.rpm.
    # (Replaces the old in-place per-arch createrepo for these repos. The extension
    # packaging may add all_avocadosdk packages to sdk/<target>, so re-render sdk too.)
    local script_dir render_tool
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    render_tool="$script_dir/render-pool-local.py"
    if [ ! -f "$render_tool" ]; then
        echo "Error: render tool not found at $render_tool" >&2
        return 1
    fi

    local subpath staged
    for subpath in "sdk/all" "sdk/$TARGET" "target/$TARGET-ext"; do
        staged="$packages_dir/$subpath"
        if [ ! -d "$staged" ] || [ -z "$(find "$staged" -name '*.rpm' -print -quit 2>/dev/null)" ]; then
            echo "  Skipping $subpath (no staged packages)"
            continue
        fi
        echo "  Rendering $subpath ..."
        if ! python3 "$render_tool" --staged "$staged" --channel-root "$releases_dir" --subpath "$subpath"; then
            echo "✗ Render failed for $subpath" >&2
            return 1
        fi
    done
    echo "✓ Extension/SDK repos rendered into the content-addressed pool ($releases_dir/_pkgs)"
    
    # Generate targets.json file from fragments
    echo "Generating targets.json file..."
    
    # Find the staging directory that matches our release
    local staging_base_dir="$REPO_DIR/staging"
    local fragments_dir=""
    local targets_json_file="$releases_dir/targets.json"
    local persistent_targets_file="$staging_base_dir/$DISTRO_CODENAME/targets.json"
    
    if [ -d "$staging_base_dir" ]; then
        # Look for staging directory matching our release ID
        local staging_dir="$staging_base_dir/$RELEASE_DIR"
        
        if [ -d "$staging_dir/fragments" ]; then
            fragments_dir="$staging_dir/fragments"
            echo "Using fragments from staging directory: $staging_dir"
        else
            # Fallback: find the most recent staging directory with fragments
            local latest_staging_dir=$(find "$staging_base_dir" -maxdepth 1 -type d -not -path "$staging_base_dir" -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)
            
            if [ -n "$latest_staging_dir" ] && [ -d "$latest_staging_dir/fragments" ]; then
                fragments_dir="$latest_staging_dir/fragments"
                echo "Using fragments from latest staging directory: $latest_staging_dir"
            fi
        fi
    fi
    
    if [ -n "$fragments_dir" ] && [ -d "$fragments_dir" ]; then
        # Count fragments to provide better feedback
        local fragment_count=$(find "$fragments_dir" -name "*-fragment.json" -type f | wc -l)
        echo "Found $fragment_count target fragment(s) in $fragments_dir"
        
        # Check for existing persistent targets.json in staging directory
        if [ -f "$persistent_targets_file" ] && [ -s "$persistent_targets_file" ]; then
            echo "Found existing persistent targets.json: $persistent_targets_file"
            echo "Will merge with existing targets to preserve all available targets"
            "$SCRIPT_DIR/repo-aggregate-targets.sh" "$fragments_dir" "$targets_json_file" "$persistent_targets_file"
        else
            echo "No existing persistent targets.json found, creating new file"
            "$SCRIPT_DIR/repo-aggregate-targets.sh" "$fragments_dir" "$targets_json_file"
        fi
        
        if [ $? -eq 0 ]; then
            echo "✓ targets.json generated successfully from $fragment_count target(s)"
            
            # Update the persistent targets.json in staging directory for future builds
            echo "Updating persistent targets.json in staging directory"
            mkdir -p "$(dirname "$persistent_targets_file")"
            cp "$targets_json_file" "$persistent_targets_file"
        else
            echo "✗ targets.json generation failed" >&2
            return 1
        fi
    else
        echo "⚠ No fragments directory found in staging, skipping targets.json generation"
        echo "  Expected location: $staging_base_dir/$RELEASE_DIR/fragments/"
        echo "  This is normal if no distro packages have been synced yet"
    fi
}

# Parse command line arguments
REPO_DIR="$DEFAULT_REPO_DIR"
DISTRO_CODENAME="$DEFAULT_DISTRO_CODENAME"
REPO_URL="$DEFAULT_REPO_URL"
CONTAINER_NAME="$DEFAULT_CONTAINER_NAME"
NETWORK_NAME="$DEFAULT_NETWORK_NAME"
RELEASE_DIR="$DEFAULT_RELEASE_DIR"
SKIP_CLEANUP="$DEFAULT_SKIP_CLEANUP"
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
# regardless of the current working directory.
if [ -n "$EXTENSIONS_DIR" ]; then
    if [ ! -d "$EXTENSIONS_DIR" ]; then
        echo "Error: extensions dir '$EXTENSIONS_DIR' not found" >&2
        exit 1
    fi
    EXTENSIONS_DIR="$(realpath "$EXTENSIONS_DIR")"
    echo "Using combined extensions directory: $EXTENSIONS_DIR"
fi

echo "=== Avocado Development Extension Packager ==="

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
# Note: Repository server is not required for packaging, only for building

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
if [ -n "$REPO_URL" ]; then
    echo "Repository URL: $REPO_URL"
fi
if [ -n "$NETWORK_NAME" ]; then
    echo "Docker network: $NETWORK_NAME"
fi
echo "Skip cleanup: $SKIP_CLEANUP"
echo ""

# Determine which extensions to package
if [ "$BUILD_ALL" = true ]; then
    echo "Packaging all extensions that support target: $TARGET"
    mapfile -t EXTENSIONS < <(get_extensions_for_target "$TARGET")
    
    if [ ${#EXTENSIONS[@]} -eq 0 ]; then
        echo "No extensions support target: $TARGET"
        exit 0
    fi
    
    echo "Extensions to package: ${EXTENSIONS[*]}"
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

# Package extensions
echo "Packaging ${#EXTENSIONS[@]} extension(s)..."
failed_extensions=()
packaged_extensions=()

for extension in "${EXTENSIONS[@]}"; do
    echo ""
    echo "--- Packaging $extension ---"
    if package_extension "$extension" "$TARGET"; then
        packaged_extensions+=("$extension")
        echo "✓ Successfully packaged extension: $extension"
    else
        echo "✗ Failed to package extension: $extension"
        echo "Stopping packaging due to failure."
        exit 1
    fi
done

# Clean up packaged extensions unless skipped
if [ "$SKIP_CLEANUP" = false ] && [ ${#packaged_extensions[@]} -gt 0 ]; then
    echo ""
    echo "--- Cleaning up extension build artifacts ---"
    for extension in "${packaged_extensions[@]}"; do
        cleanup_extension "$extension" "$TARGET"
    done
fi

echo ""

# Update metadata if any extensions were packaged successfully
if [ ${#failed_extensions[@]} -lt ${#EXTENSIONS[@]} ]; then
    update_extension_metadata
fi

# Report results
echo ""
echo "=== Packaging Complete ==="
if [ ${#failed_extensions[@]} -eq 0 ]; then
    echo "✓ All ${#EXTENSIONS[@]} extension(s) packaged successfully"
else
    echo "✓ $((${#EXTENSIONS[@]} - ${#failed_extensions[@]})) extension(s) packaged successfully"
    echo "✗ ${#failed_extensions[@]} extension(s) failed: ${failed_extensions[*]}"
fi

echo ""
echo "Extension packages available at:"
echo "  Extension packages: $REPO_DIR/packages/$DISTRO_CODENAME/target/$TARGET-ext/"
echo "  Extension releases: $REPO_DIR/releases/$DISTRO_CODENAME/$RELEASE_DIR/target/$TARGET-ext/"
echo "  SDK packages: $REPO_DIR/packages/$DISTRO_CODENAME/sdk/$TARGET/"
echo "  SDK releases: $REPO_DIR/releases/$DISTRO_CODENAME/$RELEASE_DIR/sdk/$TARGET/"
echo "  targets.json: $REPO_DIR/releases/$DISTRO_CODENAME/$RELEASE_DIR/targets.json"

if [ ${#failed_extensions[@]} -gt 0 ]; then
    exit 1
fi

