#!/usr/bin/env bash

# Exit immediately if any command fails
set -e
# Exit on undefined variables
set -u
# Propagate errors in pipelines
set -o pipefail

# Environment variables provided by avocado:
# AVOCADO_STONE_MANIFEST  - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR  - directory containing manifest-staged input images

# Read component image filenames from the manifest. The bootfiles tarball is
# yocto-static (bootloader, firmware, GPT, programmers, partition XMLs, dtb/efi
# partition vfats, initramfs). The rootfs/var images are built by avocado-cli
# at runtime — extensions applied, users configured — and injected here so the
# device flashes the runtime-correct images, not the yocto-pristine ones.
bootfiles_name=$(jq -r .storage_devices.rootdisk.images.bootfiles "$AVOCADO_STONE_MANIFEST")
rootfs_name=$(jq    -r .storage_devices.rootdisk.images.rootfs    "$AVOCADO_STONE_MANIFEST")
var_name=$(jq       -r .storage_devices.rootdisk.images.var       "$AVOCADO_STONE_MANIFEST")

bootfiles_file="${AVOCADO_STONE_DATA_DIR}/${bootfiles_name}"
rootfs_file="${AVOCADO_STONE_DATA_DIR}/${rootfs_name}"
var_file="${AVOCADO_STONE_DATA_DIR}/${var_name}"

# Stage build dir
build_dir="${AVOCADO_STONE_BUILD_DIR}/ufs"
mkdir -p "$build_dir"

# 1. Extract the static bootfiles bundle
echo "Unpacking bootfiles: $bootfiles_file"
echo "Target directory: $build_dir"
tar -xzf "$bootfiles_file" -C "$build_dir"

# 2. Inject the runtime-built rootfs as system.img (per partition_ufs.xml).
cd "$build_dir/avocado-image-rootfs"
echo "Injecting runtime rootfs as system.img"
cp "$rootfs_file" system.img

# 3. Inject the runtime-built /var. partition_ufs.xml hardcodes the avocado
#    btrfs filename, so we drop it in under that exact name.
echo "Injecting runtime /var as $var_name"
cp "$var_file" "$var_name"

# 4. Wait for QDL device on USB
echo "Waiting for QDL device..."
for i in {1..30}; do
    if lsusb | grep -q "05c6:9008"; then
        echo "QDL device found"
        sleep 1  # let it settle
        break
    fi
    if [ $i -eq 30 ]; then
        echo "ERROR: QDL device not found after 30 seconds, aborting"
        exit 1
    fi
    sleep 1
done

# 5. Flash via firehose programmer + rawprogram XMLs
qdl --storage ufs prog_firehose_ddr.elf rawprogram*.xml patch*.xml
