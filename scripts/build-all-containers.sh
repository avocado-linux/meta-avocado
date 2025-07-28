#!/usr/bin/env bash

# Don't exit on errors - we want to continue building other SDKs
set +e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Set default values for environment variables if not already set
if [ -z "$AVOCADO_REPO_BASE" ]; then
    export AVOCADO_REPO_BASE="https://repo.avocadolinux.org"
    echo "Setting AVOCADO_REPO_BASE to default: $AVOCADO_REPO_BASE"
fi

if [ -z "$DISTRO_CODENAME" ]; then
    export DISTRO_CODENAME="latest/apollo/edge"
    echo "Setting DISTRO_CODENAME to default: $DISTRO_CODENAME"
fi

echo "PROJECT_ROOT: $PROJECT_ROOT"
echo "SCRIPT_DIR: $SCRIPT_DIR"

# Store original arguments passed to this script
CLEAN_BUILD=false
PASSTHRU_ARGS=()
for arg in "$@"; do
    case $arg in
        --clean)
        CLEAN_BUILD=true
        ;;
        *)
        PASSTHRU_ARGS+=("$arg")
        ;;
    esac
done
ARGS="${PASSTHRU_ARGS[@]}"

# Arrays to track build results
SUCCESSFUL_BUILDS=()
FAILED_BUILDS=()

echo "Building all SDKs in kas/sdk directory..."
echo "Arguments passed: $ARGS"
echo

# Find all .yml files in kas/sdk directory
for sdk_config in "$PROJECT_ROOT"/kas/sdk/*.yml; do
    if [ -f "$sdk_config" ]; then
        sdk_name=$(basename "$sdk_config" .yml)
        echo "=========================================="
        echo "Building SDK: $sdk_name"
        echo "Config: $sdk_config"
        echo "=========================================="
        
        # Source the init-build script with the SDK config
        # This creates the build directory and sets up the environment
        cd "$PROJECT_ROOT"
        
        # Try to source init-build and handle potential errors
        if . scripts/init-build "$sdk_config"; then
            echo "Successfully initialized build environment for $sdk_name"
            
            if [ "$CLEAN_BUILD" = true ]; then
                echo "--> --clean specified, removing build directory"
                rm -rf ./build
            fi

            # Run kas build with the original arguments
            echo "Running: kas build $sdk_config $ARGS"
            if kas build $sdk_config $ARGS; then
                echo "✅ Build SUCCEEDED for $sdk_name"
                SUCCESSFUL_BUILDS+=("$sdk_name")
            else
                echo "❌ Build FAILED for $sdk_name"
                FAILED_BUILDS+=("$sdk_name")
            fi
        else
            echo "❌ Failed to initialize build environment for $sdk_name"
            FAILED_BUILDS+=("$sdk_name")
        fi
        
        echo
        echo "Completed build attempt for $sdk_name"
        echo
    fi
done

echo "=========================================="
echo "BUILD SUMMARY"
echo "=========================================="

echo "Total SDKs processed: $((${#SUCCESSFUL_BUILDS[@]} + ${#FAILED_BUILDS[@]}))"
echo

if [ ${#SUCCESSFUL_BUILDS[@]} -gt 0 ]; then
    echo "✅ SUCCESSFUL BUILDS (${#SUCCESSFUL_BUILDS[@]}):"
    for sdk in "${SUCCESSFUL_BUILDS[@]}"; do
        echo "  - $sdk"
    done
    echo
fi

if [ ${#FAILED_BUILDS[@]} -gt 0 ]; then
    echo "❌ FAILED BUILDS (${#FAILED_BUILDS[@]}):"
    for sdk in "${FAILED_BUILDS[@]}"; do
        echo "  - $sdk"
    done
    echo
fi

# Exit with appropriate code
if [ ${#FAILED_BUILDS[@]} -gt 0 ]; then
    echo "Some builds failed. Check the output above for details."
    exit 1
else
    echo "All builds completed successfully! 🎉"
    echo "Environment variables used:"
    echo "  AVOCADO_REPO_BASE: $AVOCADO_REPO_BASE"
    echo "  DISTRO_CODENAME: $DISTRO_CODENAME"
    exit 0
fi 
