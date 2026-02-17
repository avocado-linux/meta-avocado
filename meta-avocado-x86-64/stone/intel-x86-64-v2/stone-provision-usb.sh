#!/usr/bin/env bash

# USB Disk Provisioning Script for Intel x86-64
#
# Creates a complete disk image and writes it to an attached USB/disk device.
# This is the primary method for initial provisioning of bare-metal x86-64
# systems by cloning an Avocado OS image to a target disk.
#
# Environment variables provided by avocado/stone:
# AVOCADO_STONE_MANIFEST  - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR  - stone data directory
# AVOCADO_PROVISION_OUT   - (optional) output directory

set -e
set -u
set -o pipefail

MANIFEST="$AVOCADO_STONE_MANIFEST"
DATA_DIR="$AVOCADO_STONE_DATA_DIR"
BUILD_DIR="$AVOCADO_STONE_BUILD_DIR"
PLATFORM=$(jq -r '.runtime.platform' "$MANIFEST")

echo "=== USB Disk Provisioning for ${PLATFORM} ==="

# =============================================================================
# Step 1: Create the disk image using the img provisioning script
# =============================================================================

IMAGE_NAME="avocado-os-${PLATFORM}.img"
IMAGE_FILE="${BUILD_DIR}/${IMAGE_NAME}"

if [ ! -f "$IMAGE_FILE" ]; then
    echo "Disk image not found, creating it first..."
    echo ""

    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    IMG_SCRIPT="${SCRIPT_DIR}/stone-provision-img.sh"

    if [ ! -f "$IMG_SCRIPT" ]; then
        echo "ERROR: Cannot find stone-provision-img.sh at ${IMG_SCRIPT}"
        exit 1
    fi

    bash "$IMG_SCRIPT"
    echo ""
fi

if [ ! -f "$IMAGE_FILE" ]; then
    echo "ERROR: Disk image not found after creation: ${IMAGE_FILE}"
    exit 1
fi

IMAGE_SIZE=$(du -h "$IMAGE_FILE" | cut -f1)

# =============================================================================
# Step 2: Find the boot volume so we can hide and protect it
# =============================================================================

root_dev=""
if [ -f /proc/mounts ]; then
    root_mount=$(awk '$2 == "/" {print $1; exit}' /proc/mounts)
    if [ -n "$root_mount" ] && [ -b "$root_mount" ]; then
        root_dev=$(echo "$root_mount" | sed -E 's/p?[0-9]+$//')
        if [ "$root_dev" = "$root_mount" ]; then
            root_dev=$(echo "$root_mount" | sed 's/[0-9]*$//')
        fi
    fi
fi

# =============================================================================
# Step 3: Detect and select target device
# =============================================================================
echo ""
echo "--- Available block devices (excluding boot volume) ---"
echo ""

list_devices() {
    local found=0
    for dev in /sys/block/sd* /sys/block/nvme* /sys/block/vd* /sys/block/mmcblk*; do
        [ -e "$dev" ] || continue
        devname=$(basename "$dev")
        devpath="/dev/${devname}"

        # Hide the boot volume
        if [ -n "$root_dev" ] && [ "$devpath" = "$root_dev" ]; then
            continue
        fi

        size_sectors=$(cat "$dev/size" 2>/dev/null || echo 0)
        [ "$size_sectors" -gt 0 ] 2>/dev/null || continue

        size_gib=$(awk "BEGIN {printf \"%.1f GiB\", $size_sectors * 512 / 1073741824}")
        model=$(cat "$dev/device/model" 2>/dev/null | xargs || echo "")
        removable=$(cat "$dev/removable" 2>/dev/null || echo "0")

        # Only show removable devices
        if [ "$removable" != "1" ]; then
            continue
        fi

        printf "  /dev/%-12s %s  %s\n" "$devname" "$size_gib" "$model"
        found=1
    done

    if [ "$found" = "0" ]; then
        echo "  (no block devices found)"
    fi
}

list_devices

if [ -n "$root_dev" ]; then
    echo ""
    echo "  (boot volume ${root_dev} is hidden)"
fi
echo ""

read -p "Enter the target device path (e.g. /dev/sdX): " -r target_device 2>&1

if [ -z "$target_device" ]; then
    echo "ERROR: No device specified"
    exit 1
fi

if [ ! -b "$target_device" ]; then
    echo "ERROR: ${target_device} is not a valid block device"
    exit 1
fi

# Prevent writing to the boot volume
if [ -n "$root_dev" ] && [ "$target_device" = "$root_dev" ]; then
    echo "ERROR: ${target_device} is the boot volume -- refusing to overwrite"
    exit 1
fi

# =============================================================================
# Step 4: Safety checks
# =============================================================================

device_size_bytes=$(blockdev --getsize64 "$target_device" 2>/dev/null || echo "unknown")

echo ""
if [ "$device_size_bytes" != "unknown" ]; then
    device_size_gib=$(awk "BEGIN {printf \"%.2f\", $device_size_bytes / 1073741824}")
    devname_short=$(basename "$target_device")
    device_model=$(cat "/sys/block/${devname_short}/device/model" 2>/dev/null | xargs || echo "unknown")
    echo "Target device: ${target_device}"
    echo "  Model: ${device_model}"
    echo "  Size:  ${device_size_gib} GiB"
else
    echo "Target device: ${target_device}"
fi

echo ""
echo "WARNING: This will completely overwrite ${target_device}!"
echo "All existing data on this device will be permanently lost."
echo ""
echo "Image to write: ${IMAGE_NAME} (${IMAGE_SIZE})"
echo ""

read -p "Are you sure you want to continue? Type 'yes' to confirm: " -r confirmation 2>&1

if [ "$confirmation" != "yes" ]; then
    echo "Operation cancelled."
    exit 1
fi

# =============================================================================
# Step 5: Unmount any existing partitions
# =============================================================================
echo ""
echo "Unmounting any mounted partitions on ${target_device}..."

for part in "${target_device}"*; do
    if mountpoint -q "$part" 2>/dev/null || mount | grep -q "^${part} "; then
        echo "  Unmounting ${part}..."
        umount "$part" 2>/dev/null || true
    fi
done

# =============================================================================
# Step 6: Write image to device
# =============================================================================
echo ""
echo "Writing ${IMAGE_NAME} (${IMAGE_SIZE}) to ${target_device}..."
echo "This may take several minutes depending on the disk speed."
echo ""

# Try dd with status=progress; fall back to a background monitor
if dd if=/dev/zero of=/dev/null bs=1 count=1 status=progress 2>/dev/null; then
    dd if="$IMAGE_FILE" of="$target_device" bs=4M conv=fsync status=progress
else
    image_bytes=$(stat -c%s "$IMAGE_FILE")
    dd if="$IMAGE_FILE" of="$target_device" bs=4M conv=fsync &
    dd_pid=$!
    while kill -0 "$dd_pid" 2>/dev/null; do
        sleep 2
        written=$(cat /proc/$dd_pid/fdinfo/1 2>/dev/null | awk '/^pos:/ {print $2}' || echo "")
        if [ -n "$written" ] && [ "$written" -gt 0 ] 2>/dev/null; then
            pct=$(( written * 100 / image_bytes ))
            written_mib=$(( written / 1048576 ))
            total_mib=$(( image_bytes / 1048576 ))
            printf "\r  %d MiB / %d MiB  (%d%%)" "$written_mib" "$total_mib" "$pct"
        fi
    done
    wait "$dd_pid"
    echo ""
fi

sync

echo ""
echo "=== Provisioning complete ==="
echo ""
echo "Avocado OS has been written to ${target_device}."
echo "You may now boot the target system from this device."
echo ""
echo "The var partition can be expanded to fill the remaining disk space"
echo "by running: growpart ${target_device} 6 && btrfs filesystem resize max /var"
