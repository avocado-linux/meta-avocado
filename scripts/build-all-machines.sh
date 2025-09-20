#!/usr/bin/env bash

# Don't exit on errors - we want to continue building other machines
set +e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
echo "PROJECT_ROOT: $PROJECT_ROOT"
echo "SCRIPT_DIR: $SCRIPT_DIR"

# Store original arguments passed to this script
CLEAN_BUILD=false
SDKMACHINE="x86_64"
PASSTHRU_ARGS=()
for arg in "$@"; do
    case $arg in
        --clean)
        CLEAN_BUILD=true
        ;;
        --sdkmachine=*)
        SDKMACHINE="${arg#*=}"
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

echo "Building all machines in kas/machine directory..."
echo "Arguments passed: $ARGS"
echo "SDKMACHINE: $SDKMACHINE"
echo

# Find all .yml files in kas/machine directory
for machine_config in "$PROJECT_ROOT"/kas/machine/*.yml; do
    if [ -f "$machine_config" ]; then
        machine_name=$(basename "$machine_config" .yml)
        echo "=========================================="
        echo "Building machine: $machine_name"
        echo "Config: $machine_config"
        echo "=========================================="
        
        # Source the init-build script with the machine config
        # This creates the build directory and sets up the environment
        cd "$PROJECT_ROOT"
        
        # Try to source init-build and handle potential errors
        if . scripts/init-build "$machine_config"; then
            echo "Successfully initialized build environment for $machine_name"

            if [ "$CLEAN_BUILD" = true ]; then
                echo "--> --clean specified, removing build directory"
                rm -rf ./build
            fi
            
            # Run kas build with the original arguments
            echo "Running: SDKMACHINE=$SDKMACHINE kas build $machine_config $ARGS"
            if SDKMACHINE=$SDKMACHINE kas build $machine_config $ARGS; then
                echo "✅ Build SUCCEEDED for $machine_name"
                SUCCESSFUL_BUILDS+=("$machine_name")
            else
                echo "❌ Build FAILED for $machine_name"
                FAILED_BUILDS+=("$machine_name")
            fi
        else
            echo "❌ Failed to initialize build environment for $machine_name"
            FAILED_BUILDS+=("$machine_name")
        fi
        
        echo
        echo "Completed build attempt for $machine_name"
        echo
    fi
done

echo "=========================================="
echo "BUILD SUMMARY"
echo "=========================================="

echo "Total machines processed: $((${#SUCCESSFUL_BUILDS[@]} + ${#FAILED_BUILDS[@]}))"
echo

if [ ${#SUCCESSFUL_BUILDS[@]} -gt 0 ]; then
    echo "✅ SUCCESSFUL BUILDS (${#SUCCESSFUL_BUILDS[@]}):"
    for machine in "${SUCCESSFUL_BUILDS[@]}"; do
        echo "  - $machine"
    done
    echo
fi

if [ ${#FAILED_BUILDS[@]} -gt 0 ]; then
    echo "❌ FAILED BUILDS (${#FAILED_BUILDS[@]}):"
    for machine in "${FAILED_BUILDS[@]}"; do
        echo "  - $machine"
    done
    echo
fi

# Exit with appropriate code
if [ ${#FAILED_BUILDS[@]} -gt 0 ]; then
    echo "Some builds failed. Check the output above for details."
    exit 1
else
    echo "All builds completed successfully! 🎉"
    exit 0
fi
