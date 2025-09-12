#!/usr/bin/env bash

# Exit immediately if any command fails
set -e
# Exit on undefined variables
set -u
# Propagate errors in pipelines
set -o pipefail

# Environment variables provided by avocado:
# AVOCADO_STONE_MANIFEST - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR - stone data directory

archive_name=$(cat $AVOCADO_STONE_MANIFEST | jq -r .storage_devices.rootdisk.images.tegraflash)
archive_file="${AVOCADO_STONE_DATA_DIR}/${archive_name}"

# Create build directory for unpacking
build_dir="${AVOCADO_STONE_BUILD_DIR}/tegraflash"
mkdir -p "$build_dir"

echo "Unpacking tegraflash archive: $archive_file"
echo "Target directory: $build_dir"

# Unpack the tegraflash archive into the build directory
tar -xzf "$archive_file" -C "$build_dir"

echo "Running initrd-flash script from build directory"

# Create temporary directory for cpp wrapper
temp_bin_dir=$(mktemp -d)
trap "rm -rf '$temp_bin_dir'" EXIT

# Create cpp wrapper script that redirects to cross-compile cpp
cat > "$temp_bin_dir/cpp" << 'EOF'
#!/bin/bash
exec "${CROSS_COMPILE}cpp" "$@"
EOF
chmod +x "$temp_bin_dir/cpp"

# Add temporary directory to PATH for this execution
export PATH="$temp_bin_dir:$PATH"

# Change to build directory and run initrd-flash script
cd "$build_dir"
./initrd-flash --erase-nvme
