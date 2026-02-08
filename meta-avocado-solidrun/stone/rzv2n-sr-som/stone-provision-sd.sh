#!/usr/bin/env bash

# Avocado SD Card Provisioning — RZ/V2N SolidRun SoM
#
# Writes the Avocado system to an SD card:
#   Partition 1 — 128 MiB FAT32 boot (kernel, DTBs, firmware, initramfs)
#   Partition 2 — 2 GiB   Linux     (squashfs rootfs)
#   Partition 3 — 512 MiB Linux     (btrfs var, expanded at runtime)
#
# Environment variables provided by stone:
#   AVOCADO_STONE_MANIFEST  — path to manifest JSON file
#   AVOCADO_STONE_BUILD_DIR — build output directory (_build inside stone output)
#   AVOCADO_STONE_DATA_DIR  — stone data directory
#   AVOCADO_DEVICE_CERT     — device certificate (base64-encoded PEM)
#   AVOCADO_DEVICE_KEY      — device private key (base64-encoded PEM)
#   AVOCADO_DEVICE_ID       — device ID

set -e
set -u
set -o pipefail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

die() { echo "Error: $*" >&2; exit 1; }

# Return partition device path for a given disk and partition number.
#   /dev/sda  + 1  →  /dev/sda1
#   /dev/mmcblk0 + 1 → /dev/mmcblk0p1
part_dev() {
    local disk="$1" num="$2"
    if [[ "$disk" =~ [0-9]$ ]]; then
        echo "${disk}p${num}"
    else
        echo "${disk}${num}"
    fi
}

# List block devices that look like physical disks (sd* and mmcblk*).
list_disk_devices() {
    lsblk -dpno NAME 2>/dev/null | grep -E '/dev/sd[a-z]$|/dev/mmcblk[0-9]+$' || true
}

# ---------------------------------------------------------------------------
# Locate images
# ---------------------------------------------------------------------------

manifest="$AVOCADO_STONE_MANIFEST"
build_dir="$AVOCADO_STONE_BUILD_DIR"
data_dir="$AVOCADO_STONE_DATA_DIR"

# boot.img is built by stone (mkfat) and placed in _build
boot_img="${build_dir}/boot.img"
[[ -f "$boot_img" ]] || die "boot.img not found in build dir: $build_dir"

# rootfs and var images are in the stone data directory
rootfs_name=$(jq -r '.storage_devices.rootdisk.images.rootfs' "$manifest")
var_name=$(jq -r '.storage_devices.rootdisk.images.var' "$manifest")

rootfs_img="${data_dir}/${rootfs_name}"
var_img="${data_dir}/${var_name}"

[[ -f "$rootfs_img" ]] || die "rootfs image not found: $rootfs_img"
[[ -f "$var_img" ]] || die "var image not found: $var_img"

echo ""
echo "=========================================="
echo "Avocado SD Card Provisioning"
echo "RZ/V2N SolidRun SoM"
echo "=========================================="
echo ""
echo "Images:"
echo "  boot   : $boot_img"
echo "  rootfs : $rootfs_img"
echo "  var    : $var_img"
echo ""

# ---------------------------------------------------------------------------
# Detect SD card
# ---------------------------------------------------------------------------

echo "Recording existing block devices..."
existing_devices=$(list_disk_devices)

if [[ -n "$existing_devices" ]]; then
    echo "Existing devices:"
    echo "$existing_devices" | sed 's/^/  /'
else
    echo "Existing devices: none"
fi

echo ""
read -p "Please insert your SD card and press Enter to continue..." -r

echo "Waiting for new block device..."

TIMEOUT=60
start_time=$(date +%s)
sd_device=""

while [[ -z "$sd_device" ]]; do
    current_devices=$(list_disk_devices)
    new_device=$(comm -13 <(echo "$existing_devices") <(echo "$current_devices") | head -1)

    if [[ -n "$new_device" ]]; then
        sd_device="$new_device"
        echo ""
        echo "Detected new device: $sd_device"
        break
    fi

    now=$(date +%s)
    if (( now - start_time >= TIMEOUT )); then
        echo ""
        echo "Timed out after ${TIMEOUT}s waiting for SD card."
        echo "Currently visible devices:"
        list_disk_devices | sed 's/^/  /'
        die "No new SD card detected"
    fi

    echo -n "."
    sleep 1
done

# Wait for the device to settle
echo "Waiting for device to be ready..."
sleep 2

if ! dd if="$sd_device" of=/dev/null bs=512 count=1 2>/dev/null; then
    die "Device $sd_device is not readable"
fi

# Show device info
dev_size_bytes=$(lsblk -bdno SIZE "$sd_device" 2>/dev/null || echo 0)
dev_size_gib=$(echo "scale=2; $dev_size_bytes / 1073741824" | bc -l 2>/dev/null || echo "?")
echo ""
echo "SD card detected:"
echo "  Device : $sd_device"
echo "  Size   : ${dev_size_gib} GiB"

block_dev="/sys/block/$(basename "$sd_device")"
if [[ -d "$block_dev/device" ]]; then
    vendor=$(cat "$block_dev/device/vendor" 2>/dev/null | xargs || true)
    model=$(cat "$block_dev/device/model" 2>/dev/null | xargs || true)
    [[ -n "$vendor" ]] && echo "  Vendor : $vendor"
    [[ -n "$model" ]]  && echo "  Model  : $model"
fi

# ---------------------------------------------------------------------------
# Confirm
# ---------------------------------------------------------------------------

echo ""
echo "WARNING: This will completely erase $sd_device!"
echo "All data on this ${dev_size_gib} GiB device will be lost."
echo ""
read -p "Are you sure you want to continue? (y/N): " -r

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 1
fi

# Unmount any existing partitions
if mount | grep -q "$sd_device"; then
    echo "Unmounting partitions on ${sd_device}..."
    umount "${sd_device}"* 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# Partition the SD card (MBR)
# ---------------------------------------------------------------------------

echo ""
echo "Creating partition table..."

# Partition layout (512-byte sectors):
#   Partition 1: 128 MiB FAT32/LBA, bootable, starts at 2 MiB
#   Partition 2: 2 GiB   Linux
#   Partition 3: 512 MiB Linux
sfdisk --quiet --wipe always "$sd_device" <<'PARTS'
label: dos

start=4096, size=262144, type=c, bootable
size=4194304, type=83
size=1048576, type=83
PARTS

echo "Partition table written."

# Let the kernel re-read the partition table
partprobe "$sd_device" 2>/dev/null || true
sleep 2

# Verify partitions appeared
for n in 1 2 3; do
    p=$(part_dev "$sd_device" "$n")
    [[ -b "$p" ]] || die "Partition device $p did not appear"
done

p1=$(part_dev "$sd_device" 1)
p2=$(part_dev "$sd_device" 2)
p3=$(part_dev "$sd_device" 3)

# ---------------------------------------------------------------------------
# Write boot partition (dd the pre-built boot.img)
# ---------------------------------------------------------------------------

echo ""
echo "Writing boot image to ${p1}..."
dd if="$boot_img" of="$p1" bs=1M status=progress conv=fsync

echo "Boot partition written."

# ---------------------------------------------------------------------------
# Write rootfs and var images
# ---------------------------------------------------------------------------

echo ""
echo "Writing rootfs image to ${p2}..."
dd if="$rootfs_img" of="$p2" bs=1M status=progress conv=fsync

echo ""
echo "Writing var image to ${p3}..."
dd if="$var_img" of="$p3" bs=1M status=progress conv=fsync

sync

echo ""
echo "=========================================="
echo "SD card written successfully!"
echo "You can now safely remove the card and boot your device."
echo "=========================================="

exit 0
