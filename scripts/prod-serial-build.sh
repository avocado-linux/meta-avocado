#!/usr/bin/env bash

# Don't exit on errors - we want to continue building other configurations
set +e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
echo "PROJECT_ROOT: $PROJECT_ROOT"
echo "SCRIPT_DIR: $SCRIPT_DIR"

# Path to targets.json
TARGETS_JSON="$PROJECT_ROOT/../.github/data/targets.json"

if [ ! -f "$TARGETS_JSON" ]; then
    echo "ERROR: targets.json not found at $TARGETS_JSON"
    exit 1
fi

echo "Reading production targets from $TARGETS_JSON"
echo

# Parse targets from JSON (using jq if available, otherwise python)
if command -v jq &> /dev/null; then
    TARGETS=($(jq -r '.[]' "$TARGETS_JSON"))
else
    # Fallback to python if jq is not available
    TARGETS=($(python3 -c "import json; import sys; data = json.load(open('$TARGETS_JSON')); print('\n'.join(data))"))
fi

if [ ${#TARGETS[@]} -eq 0 ]; then
    echo "ERROR: No targets found in targets.json"
    exit 1
fi

echo "Found ${#TARGETS[@]} production targets:"
for target in "${TARGETS[@]}"; do
    echo "  - $target"
done
echo

# Arrays to track build results
SUCCESSFUL_BUILDS=()
FAILED_BUILDS=()

# Build configurations to run for each target
declare -A BUILD_CONFIGS
BUILD_CONFIGS=(
    ["avocado-distro"]="x86_64:avocado-distro"
    ["avocado-sdk-aarch64"]="aarch64:avocado-sdk"
    ["avocado-sdk-x86_64"]="x86_64:avocado-sdk"
)

echo "=========================================="
echo "PRODUCTION SERIAL BUILD - CACHE PRIMING"
echo "=========================================="
echo

# Iterate through each target
for target in "${TARGETS[@]}"; do
    machine_config="$PROJECT_ROOT/kas/machine/${target}.yml"
    
    if [ ! -f "$machine_config" ]; then
        echo "⚠️  WARNING: Machine config not found for $target at $machine_config"
        echo "    Skipping $target"
        echo
        continue
    fi
    
    echo "=========================================="
    echo "Building target: $target"
    echo "Config: $machine_config"
    echo "=========================================="
    
    # Initialize build environment
    cd "$PROJECT_ROOT"
    
    if ! . scripts/init-build "$machine_config"; then
        echo "❌ Failed to initialize build environment for $target"
        FAILED_BUILDS+=("$target:init")
        echo
        continue
    fi
    
    # Run each build configuration
    for config_name in "${!BUILD_CONFIGS[@]}"; do
        IFS=':' read -r sdkmachine build_target <<< "${BUILD_CONFIGS[$config_name]}"
        
        echo "------------------------------------------"
        echo "Building: $target - $config_name"
        echo "  SDKMACHINE: $sdkmachine"
        echo "  Target: $build_target"
        echo "------------------------------------------"
        
        # Clean the build directory before each build
        echo "Cleaning ./build directory..."
        rm -rf ./build
        
        # Run kas build
        if SDKMACHINE=$sdkmachine kas build --target "$build_target" "$machine_config"; then
            echo "✅ Build SUCCEEDED for $target - $config_name"
            SUCCESSFUL_BUILDS+=("$target:$config_name")
        else
            echo "❌ Build FAILED for $target - $config_name"
            FAILED_BUILDS+=("$target:$config_name")
        fi
        
        echo
    done
    
    echo "Completed all build configurations for $target"
    echo
done

echo "=========================================="
echo "BUILD SUMMARY"
echo "=========================================="

total_builds=$((${#SUCCESSFUL_BUILDS[@]} + ${#FAILED_BUILDS[@]}))
echo "Total build configurations attempted: $total_builds"
echo

if [ ${#SUCCESSFUL_BUILDS[@]} -gt 0 ]; then
    echo "✅ SUCCESSFUL BUILDS (${#SUCCESSFUL_BUILDS[@]}):"
    for build in "${SUCCESSFUL_BUILDS[@]}"; do
        echo "  - $build"
    done
    echo
fi

if [ ${#FAILED_BUILDS[@]} -gt 0 ]; then
    echo "❌ FAILED BUILDS (${#FAILED_BUILDS[@]}):"
    for build in "${FAILED_BUILDS[@]}"; do
        echo "  - $build"
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

