#!/usr/bin/env bash

set -e # Exit immediately if a command exits with a non-zero status.

# Directory of this script, so sibling repo-*/render helpers resolve regardless of cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Default configuration
DEFAULT_REPO_DIR="/tmp/avocado-dev-repo"
DEFAULT_DISTRO_CODENAME="2026/edge"
DEFAULT_RELEASE_ID="dev-$(date -u '+%Y%m%d-%H%M%S')"

# Function to show usage
usage() {
    cat << EOF
Usage: $0 [OPTIONS] <target>

Sync packages from a build target to a development repository.

Arguments:
    target              Target name (e.g., qemux86-64, raspberrypi4)

Options:
    -r, --repo-dir DIR      Repository directory (default: $DEFAULT_REPO_DIR)
    -d, --distro CODENAME   Distribution codename (default: $DEFAULT_DISTRO_CODENAME)
    -i, --release-id ID     Release identifier (default: auto-generated timestamp)
    -b, --build-dir DIR     Build directory (default: build-<target>)
    -c, --container-name NAME   Repository container name (default: avocado-dev-repo)
    -h, --help              Show this help message

Examples:
    $0 qemux86-64
    $0 -r /opt/avocado-repo -d 2026/edge -i my-dev-build qemux86-64
    $0 --repo-dir /opt/avocado-repo --release-id stable-build raspberrypi4

This script:
1. Finds the build directory for the target (build-<target>)
2. Reads the avocado-repo.map file from build-<target>/build/tmp/deploy/rpm
3. Syncs packages to the specified repository directory
4. Generates target fragment for targets.json
5. Updates repository metadata for distro packages (excludes extensions)

The repository structure will be:
    <repo-dir>/
    ├── packages/<distro-codename>/     # Aggregated packages
    └── releases/<distro-codename>/     # Repository metadata

EOF
}

# Parse command line arguments
REPO_DIR="$DEFAULT_REPO_DIR"
DISTRO_CODENAME="$DEFAULT_DISTRO_CODENAME"
RELEASE_ID="$DEFAULT_RELEASE_ID"
BUILD_DIR=""
TARGET=""
CONTAINER_NAME="avocado-dev-repo"

while [[ $# -gt 0 ]]; do
    case $1 in
        -r|--repo-dir)
            REPO_DIR="$2"
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
        -b|--build-dir)
            BUILD_DIR="$2"
            shift 2
            ;;
        -c|--container-name)
            CONTAINER_NAME="$2"
            shift 2
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
            if [ -z "$TARGET" ]; then
                TARGET="$1"
            else
                echo "Error: Multiple targets specified" >&2
                usage >&2
                exit 1
            fi
            shift
            ;;
    esac
done

# Validate required arguments
if [ -z "$TARGET" ]; then
    echo "Error: Target is required" >&2
    usage >&2
    exit 1
fi

# Set default build directory if not specified
if [ -z "$BUILD_DIR" ]; then
    BUILD_DIR="build-$TARGET"
fi

# Validate build directory exists
if [ ! -d "$BUILD_DIR" ]; then
    echo "Error: Build directory '$BUILD_DIR' not found" >&2
    echo "Have you built the target '$TARGET'? Expected directory: $BUILD_DIR" >&2
    exit 1
fi

# Set up paths
SOURCE_DEPLOY_DIR="$BUILD_DIR/build/tmp/deploy/rpm"
PACKAGES_PATH="$REPO_DIR/packages"
RELEASES_PATH="$REPO_DIR/releases/$DISTRO_CODENAME/$RELEASE_ID"

# Validate source directory exists
if [ ! -d "$SOURCE_DEPLOY_DIR" ]; then
    echo "Error: Source deploy directory '$SOURCE_DEPLOY_DIR' not found" >&2
    echo "Have you completed the build for target '$TARGET'?" >&2
    exit 1
fi

# Validate map file exists
MAP_FILE="$SOURCE_DEPLOY_DIR/avocado-repo.map"
if [ ! -f "$MAP_FILE" ]; then
    echo "Error: Map file not found at '$MAP_FILE'" >&2
    echo "The build may not have completed successfully." >&2
    exit 1
fi

echo "=== Avocado Development Package Sync ==="
echo "Target: $TARGET"
echo "Build directory: $BUILD_DIR"
echo "Source deploy directory: $SOURCE_DEPLOY_DIR"
echo "Repository directory: $REPO_DIR"
echo "Packages path: $PACKAGES_PATH"
echo "Releases path: $RELEASES_PATH"
echo "Distribution codename: $DISTRO_CODENAME"
echo "Release ID: $RELEASE_ID"
echo ""

# Create target directories
echo "Creating target directories..."
mkdir -p "$PACKAGES_PATH"
mkdir -p "$RELEASES_PATH"

# Stage packages using the existing script
echo "Staging packages from build to repository..."
"$SCRIPT_DIR/repo-stage-rpms.sh" "$SOURCE_DEPLOY_DIR" "$PACKAGES_PATH" "$DISTRO_CODENAME"

if [ $? -eq 0 ]; then
    echo "✓ Package staging completed successfully"
else
    echo "✗ Package staging failed" >&2
    exit 1
fi

# Generate target fragment for targets.json
echo ""
echo "Generating target fragment for targets.json..."
STAGING_DIR="$REPO_DIR/staging/$RELEASE_ID"
FRAGMENTS_DIR="$STAGING_DIR/fragments"
mkdir -p "$FRAGMENTS_DIR"

"$SCRIPT_DIR/repo-generate-target-fragment.sh" "$SOURCE_DEPLOY_DIR" "$TARGET" "$FRAGMENTS_DIR" "$DISTRO_CODENAME"

if [ $? -eq 0 ]; then
    echo "✓ Target fragment generated successfully"
else
    echo "✗ Target fragment generation failed" >&2
    exit 1
fi

# Render the repositories to mirror the PRODUCTION content-addressed-pool layout:
# pool every package once into <release>/_pkgs/<aa>/<sha>.rpm and write per-repo
# metadata whose primary.xml references the pool (../../_pkgs/<aa>/<sha>.rpm),
# exactly like the cloud render_pool. The release dir is the served channel root,
# so _pkgs/ and the repos sit as siblings under it. (Replaces the old in-place
# per-repo createrepo; the staged packages/ tree is now build-input only.)
echo ""
echo "Rendering pooled repositories (mirrors production render)..."

RENDER_TOOL="$SCRIPT_DIR/render-pool-local.py"
if [ ! -f "$RENDER_TOOL" ]; then
    echo "Error: render tool not found at $RENDER_TOOL" >&2
    exit 1
fi

rendered_any=false
while IFS='=' read -r key value || [ -n "$key" ]; do
    [ "$key" = "repo" ] || continue
    # Strip the literal "$releasever/" prefix -> path relative to the channel root.
    rel_root="${value#\$releasever/}"
    # Extension repos are rendered by dev-build-extensions.sh; skip here.
    case "$rel_root" in
        target/*-ext) continue ;;
    esac

    staged="$PACKAGES_PATH/$DISTRO_CODENAME/$rel_root"
    if [ ! -d "$staged" ]; then
        echo "  Skipping $rel_root (no staged packages at $staged)"
        continue
    fi

    echo "  Rendering $rel_root ..."
    if ! python3 "$RENDER_TOOL" --staged "$staged" --channel-root "$RELEASES_PATH" --subpath "$rel_root"; then
        echo "✗ Render failed for $rel_root" >&2
        exit 1
    fi
    rendered_any=true
done < "$MAP_FILE"

if [ "$rendered_any" != true ]; then
    echo "✗ No repositories rendered (no repo= roots in $MAP_FILE)" >&2
    exit 1
fi
echo "✓ Repositories rendered into the content-addressed pool ($RELEASES_PATH/_pkgs)"

echo ""
echo "=== Sync Complete ==="
echo "Packages synced to: $PACKAGES_PATH"
echo "Metadata generated at: $RELEASES_PATH"
echo "Staging directory: $STAGING_DIR"
echo "Target fragment generated at: $FRAGMENTS_DIR/$TARGET-fragment.json"
echo ""
echo "Next steps:"
echo "1. Start package repository server: ./scripts/dev-start-repo.sh -r '$REPO_DIR'"
echo "2. Build extensions: ./scripts/dev-build-extensions.sh -r '$REPO_DIR' -t '$TARGET'"
echo "   (This will aggregate fragments into targets.json)"
echo ""
