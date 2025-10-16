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

archive_name=$(cat $AVOCADO_STONE_MANIFEST | jq -r .storage_devices.rootdisk.images.ufs)
archive_file="${AVOCADO_STONE_DATA_DIR}/${archive_name}"

# Create build directory for unpacking
build_dir="${AVOCADO_STONE_BUILD_DIR}/ufs"
mkdir -p "$build_dir"

echo "Unpacking ufs image: $archive_file"
echo "Target directory: $build_dir"
tar -xzf "$archive_file" -C "$build_dir"

echo "Running qdl binary from build directory"
cd "$build_dir/avocado-image-rootfs"
./qdl --storage ufs prog_firehose_ddr.elf rawprogram*.xml patch*.xml
