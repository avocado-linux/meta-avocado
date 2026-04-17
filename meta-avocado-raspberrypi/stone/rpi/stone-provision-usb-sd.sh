#!/usr/bin/env bash

# RPi SD card provisioning via rpiboot USB mass storage.
#
# This script provisions an SD card in an RPi's SD slot by:
# 1. Extracting images from the stone archive
# 2. Creating a disk image with MBR+extended partition table
# 3. Patching the U-Boot environment with device-specific values
# 4. Using rpiboot to expose the SD card as USB mass storage
# 5. Writing the image to the SD card

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/stone-tryboot-common.sh"
source "${SCRIPT_DIR}/stone-rpiboot-common.sh"

# Environment variables provided by avocado:
# AVOCADO_STONE_MANIFEST - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR - stone data directory
# AVOCADO_DEVICE_CERT - device certificate content (base64 encoded pem)
# AVOCADO_DEVICE_KEY - device private key content (base64 encoded pem)
# AVOCADO_DEVICE_ID - device ID

echo "=== RPi SD Card Provisioning via rpiboot (tryboot) ==="

# --- Step 1: Extract archive and build disk image ---
archive_name=$(jq -r .storage_devices.rootdisk.out "$AVOCADO_STONE_MANIFEST")
archive_file="${AVOCADO_STONE_BUILD_DIR}/${archive_name}"
archive_image="${archive_file%%.*}.img"

if [[ -z "$archive_name" || "$archive_name" == "null" ]]; then
    echo "Error: Could not extract archive name from manifest"
    exit 1
fi

if [[ ! -f "$archive_file" ]]; then
    echo "Error: Archive file not found: $archive_file"
    exit 1
fi

# Always rebuild — different profiles patch differently
echo "Extracting archive and building disk image..."
rm -f "${archive_image}"
extract_archive "$archive_file" "$AVOCADO_STONE_BUILD_DIR"
create_tryboot_disk_image "$AVOCADO_STONE_MANIFEST" "$AVOCADO_STONE_BUILD_DIR" "$archive_image"

# --- Step 2: Patch U-Boot env ---
echo "Patching U-Boot environment for SD card..."
patch_uboot_env "$archive_image" "$AVOCADO_STONE_MANIFEST" \
    avocado_device_id "${AVOCADO_DEVICE_ID:-}" \
    avocado_device_cert "${AVOCADO_DEVICE_CERT:-}" \
    avocado_device_key "${AVOCADO_DEVICE_KEY:-}" \
    a.avocado_platform "$(jq -r .runtime.platform "$AVOCADO_STONE_MANIFEST")" \
    a.avocado_architecture "$(jq -r .runtime.architecture "$AVOCADO_STONE_MANIFEST")"
echo "U-Boot env patched"

# --- Step 3: Detect rpiboot device and enter mass storage mode ---
rpiboot_detect_and_expose

# --- Step 4: Write the patched image ---
echo "Writing system image to SD card..."

if mount | grep -q "${rpi_block_device}"; then
    umount "${rpi_block_device}"* 2>/dev/null || true
fi

sleep 2

if ! dd if="${rpi_block_device}" of=/dev/null bs=512 count=1 2>/dev/null; then
    echo "Error: Device ${rpi_block_device} is not accessible"
    exit 1
fi

image_size=$(stat -c%s "${archive_image}" 2>/dev/null || stat -f%z "${archive_image}" 2>/dev/null || echo "unknown")
image_size_mib=$((${image_size:-0} / 1024 / 1024))
echo "Writing ${image_size_mib} MiB to ${rpi_block_device}..."

if ! dd if="${archive_image}" of="${rpi_block_device}" bs=4M status=progress conv=fsync; then
    echo "Error: Failed to write system image to SD card"
    exit 1
fi
echo "Write complete. Syncing..."
sync

echo ""
echo "=== SD card provisioning complete ==="
echo "Please disconnect the USB cable and power cycle the device."

exit 0
