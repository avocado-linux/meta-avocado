#!/usr/bin/env bash

# Disk Image Provisioning Script for Intel x86-64
#
# Creates a complete GPT disk image with EFI System Partition,
# A/B rootfs partitions, recovery, and data partition.
#
# Environment variables provided by avocado/stone:
# AVOCADO_STONE_MANIFEST  - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR  - stone data directory
# AVOCADO_PROVISION_OUT   - (optional) output directory for final image

set -e
set -u
set -o pipefail

MANIFEST="$AVOCADO_STONE_MANIFEST"
DATA_DIR="$AVOCADO_STONE_DATA_DIR"
BUILD_DIR="$AVOCADO_STONE_BUILD_DIR"

# Read image filenames from manifest
ROOTFS_IMAGE=$(jq -r '.storage_devices.rootdisk.images.rootfs' "$MANIFEST")
VAR_IMAGE=$(jq -r '.storage_devices.rootdisk.images.var' "$MANIFEST")
INITRAMFS_IMAGE=$(jq -r '.storage_devices.rootdisk.images.initramfs' "$MANIFEST")
KERNEL_IMAGE=$(jq -r '.storage_devices.rootdisk.images.kernel' "$MANIFEST")
BOOTLOADER_IMAGE=$(jq -r '.storage_devices.rootdisk.images.bootloader' "$MANIFEST")
PLATFORM=$(jq -r '.runtime.platform' "$MANIFEST")

echo "=== Creating disk image for ${PLATFORM} ==="
echo "  Data directory: ${DATA_DIR}"
echo "  Build directory: ${BUILD_DIR}"

# Validate required files exist
for img in "$ROOTFS_IMAGE" "$VAR_IMAGE" "$INITRAMFS_IMAGE" "$KERNEL_IMAGE" "$BOOTLOADER_IMAGE"; do
    if [ ! -f "${DATA_DIR}/${img}" ]; then
        echo "ERROR: Required image not found: ${DATA_DIR}/${img}"
        exit 1
    fi
done

# =============================================================================
# Partition layout (all sizes in MiB)
# =============================================================================
# GPT overhead: 1 MiB at start
# Partition 1: ESP / boot-a  (FAT32, 256 MiB) - EFI System Partition
# Partition 2: boot-b        (FAT32, 256 MiB) - A/B standby boot
# Partition 3: recovery      (FAT32, 256 MiB) - Recovery boot
# Partition 4: rootfs-a      (squashfs)       - sized to image + padding
# Partition 5: rootfs-b      (squashfs)       - same size as rootfs-a
# Partition 6: var           (btrfs)          - 512 MiB minimum, expandable
# =============================================================================

ESP_SIZE_MIB=256
RECOVERY_SIZE_MIB=256
VAR_SIZE_MIB=512
GPT_START_MIB=1

# Calculate rootfs partition size (round up to next MiB + 16 MiB padding)
ROOTFS_FILE="${DATA_DIR}/${ROOTFS_IMAGE}"
ROOTFS_BYTES=$(stat -c%s "$ROOTFS_FILE")
ROOTFS_SIZE_MIB=$(( (ROOTFS_BYTES / 1048576) + 16 ))

# Calculate total image size
TOTAL_MIB=$(( GPT_START_MIB + ESP_SIZE_MIB + ESP_SIZE_MIB + RECOVERY_SIZE_MIB + ROOTFS_SIZE_MIB + ROOTFS_SIZE_MIB + VAR_SIZE_MIB + 1 ))

IMAGE_NAME="avocado-os-${PLATFORM}.img"
IMAGE_FILE="${BUILD_DIR}/${IMAGE_NAME}"

echo "  ESP size:    ${ESP_SIZE_MIB} MiB"
echo "  Rootfs size: ${ROOTFS_SIZE_MIB} MiB"
echo "  Var size:    ${VAR_SIZE_MIB} MiB"
echo "  Total image: ${TOTAL_MIB} MiB"

# =============================================================================
# Create raw disk image
# =============================================================================
echo ""
echo "=== Creating raw disk image ==="
truncate -s "${TOTAL_MIB}M" "$IMAGE_FILE"

# =============================================================================
# Create GPT partition table
# =============================================================================
echo "=== Creating GPT partition table ==="

OFFSET=${GPT_START_MIB}

# ESP / boot-a
BOOT_A_START=${OFFSET}
BOOT_A_END=$(( OFFSET + ESP_SIZE_MIB - 1 ))
OFFSET=$(( OFFSET + ESP_SIZE_MIB ))

# boot-b
BOOT_B_START=${OFFSET}
BOOT_B_END=$(( OFFSET + ESP_SIZE_MIB - 1 ))
OFFSET=$(( OFFSET + ESP_SIZE_MIB ))

# recovery
RECOVERY_START=${OFFSET}
RECOVERY_END=$(( OFFSET + RECOVERY_SIZE_MIB - 1 ))
OFFSET=$(( OFFSET + RECOVERY_SIZE_MIB ))

# rootfs-a
ROOTFS_A_START=${OFFSET}
ROOTFS_A_END=$(( OFFSET + ROOTFS_SIZE_MIB - 1 ))
OFFSET=$(( OFFSET + ROOTFS_SIZE_MIB ))

# rootfs-b
ROOTFS_B_START=${OFFSET}
ROOTFS_B_END=$(( OFFSET + ROOTFS_SIZE_MIB - 1 ))
OFFSET=$(( OFFSET + ROOTFS_SIZE_MIB ))

# var (remainder)
VAR_START=${OFFSET}
VAR_END=$(( OFFSET + VAR_SIZE_MIB - 1 ))

# sgdisk type codes
# EF00 = EFI System Partition
# 8304 = Linux x86-64 root (Discoverable Partitions Spec)
# 8300 = Linux filesystem

VAR_PARTUUID="4d21b016-b534-45c2-a9fb-5c16e091fd2d"

sgdisk --zap-all "$IMAGE_FILE"
sgdisk \
    -n "1:$(( BOOT_A_START * 2048 )):+$(( ESP_SIZE_MIB * 2048 - 1 ))" -t 1:EF00 -c 1:"boot-a" \
    -n "2:$(( BOOT_B_START * 2048 )):+$(( ESP_SIZE_MIB * 2048 - 1 ))" -t 2:EF00 -c 2:"boot-b" \
    -n "3:$(( RECOVERY_START * 2048 )):+$(( RECOVERY_SIZE_MIB * 2048 - 1 ))" -t 3:EF00 -c 3:"recovery" \
    -n "4:$(( ROOTFS_A_START * 2048 )):+$(( ROOTFS_SIZE_MIB * 2048 - 1 ))" -t 4:8304 -c 4:"rootfs-a" \
    -n "5:$(( ROOTFS_B_START * 2048 )):+$(( ROOTFS_SIZE_MIB * 2048 - 1 ))" -t 5:8304 -c 5:"rootfs-b" \
    -n "6:$(( VAR_START * 2048 )):+$(( VAR_SIZE_MIB * 2048 - 1 ))" -t 6:8300 -c 6:"var" -u "6:${VAR_PARTUUID}" \
    "$IMAGE_FILE"

echo "  Partition table created"

# =============================================================================
# Create ESP (FAT32) boot image with EFI bootloader, kernel, and initramfs
# =============================================================================
echo "=== Creating ESP boot image ==="

ESP_IMG="${BUILD_DIR}/esp-boot.img"
truncate -s "${ESP_SIZE_MIB}M" "$ESP_IMG"
mkfs.fat -F 32 -n "BOOT-A" "$ESP_IMG"

# Create EFI directory structure and copy files
ESP_MNT=$(mktemp -d)
trap "umount '$ESP_MNT' 2>/dev/null || true; rmdir '$ESP_MNT' 2>/dev/null || true" EXIT

if command -v mcopy >/dev/null 2>&1; then
    # Use mtools if available (no root required)
    mmd -i "$ESP_IMG" ::EFI
    mmd -i "$ESP_IMG" ::EFI/BOOT
    mcopy -i "$ESP_IMG" "${DATA_DIR}/${BOOTLOADER_IMAGE}" "::EFI/BOOT/BOOTX64.EFI"
    mcopy -i "$ESP_IMG" "${DATA_DIR}/${KERNEL_IMAGE}" "::bzImage"
    mcopy -i "$ESP_IMG" "${DATA_DIR}/${INITRAMFS_IMAGE}" "::initramfs.cpio.zst"

    # Create systemd-boot loader config
    mmd -i "$ESP_IMG" ::loader
    mmd -i "$ESP_IMG" ::loader/entries

    LOADER_CONF=$(mktemp)
    echo "default avocado.conf" > "$LOADER_CONF"
    echo "timeout 3" >> "$LOADER_CONF"
    mcopy -i "$ESP_IMG" "$LOADER_CONF" "::loader/loader.conf"
    rm -f "$LOADER_CONF"

    ENTRY_CONF=$(mktemp)
    cat > "$ENTRY_CONF" <<ENTRY
title   Avocado OS
linux   /bzImage
initrd  /initramfs.cpio.zst
options root=PARTLABEL=rootfs-a ro earlycon=efifb console=ttyS0,115200n8 console=tty0 nomodeset keep_bootcon
ENTRY
    mcopy -i "$ESP_IMG" "$ENTRY_CONF" "::loader/entries/avocado.conf"
    rm -f "$ENTRY_CONF"
else
    echo "ERROR: mtools (mcopy) not found - required for ESP image creation"
    exit 1
fi

echo "  ESP boot image created"

# =============================================================================
# Write partition images into disk image
# =============================================================================
echo "=== Writing partition images ==="

# Write ESP to boot-a
dd if="$ESP_IMG" of="$IMAGE_FILE" bs=1M seek=${BOOT_A_START} conv=notrunc status=progress
echo "  boot-a (ESP) written"

# Write rootfs-a
dd if="$ROOTFS_FILE" of="$IMAGE_FILE" bs=1M seek=${ROOTFS_A_START} conv=notrunc status=progress
echo "  rootfs-a written"

# Write var
dd if="${DATA_DIR}/${VAR_IMAGE}" of="$IMAGE_FILE" bs=1M seek=${VAR_START} conv=notrunc status=progress
echo "  var written"

# Cleanup
rm -f "$ESP_IMG"
trap - EXIT

echo ""
echo "=== Disk image created: ${IMAGE_FILE} ==="
echo "  Size: $(du -h "$IMAGE_FILE" | cut -f1)"

# Copy to output directory if specified
if [ -n "${AVOCADO_PROVISION_OUT:-}" ]; then
    mkdir -p "$AVOCADO_PROVISION_OUT"
    cp -v "$IMAGE_FILE" "$AVOCADO_PROVISION_OUT/"
    echo "  Copied to: ${AVOCADO_PROVISION_OUT}/${IMAGE_NAME}"
fi
