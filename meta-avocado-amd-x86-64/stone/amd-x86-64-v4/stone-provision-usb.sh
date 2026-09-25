#!/usr/bin/env bash

# USB Disk Provisioning Script for AMD x86-64
#
# Creates a complete disk image and writes it to an attached USB/disk device.
# This is the primary method for initial provisioning of bare-metal x86-64
# systems by cloning an Avocado OS image to a target disk.
#
# Environment variables provided by avocado/stone:
# AVOCADO_STONE_MANIFEST  - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_PROVISION_OUT   - (optional) output directory

set -e
set -u
set -o pipefail

MANIFEST="$AVOCADO_STONE_MANIFEST"
# Never read below, but the assignment is load-bearing under `set -u`: it aborts
# the script here if stone did not export AVOCADO_STONE_DATA_DIR, rather than
# part-way through writing a disk.
# shellcheck disable=SC2034
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
image_bytes=$(stat -c%s "$IMAGE_FILE")

sysblock=${AVOCADO_PROVISION_SYSBLOCK:-/sys/class/block}

die() {
    echo "ERROR: $*"
    exit 1
}

# =============================================================================
# Step 2: Find the devices the running system lives on
# =============================================================================
# Every block device under / - partitions, dm-crypt, LVM, md and the physical
# disks beneath them - so a target that is any of them is refused however it
# is spelled. A root on overlay, tmpfs or NFS has no backing disk here.

# --nofsroot drops the "[/@]" a btrfs subvolume or bind mount appends to SOURCE.
root_src=$(findmnt -n --nofsroot -o SOURCE / 2>/dev/null || true)
case "$root_src" in
    //*) root_src="" ;; # CIFS share, no local disk
    /*)
        if [ ! -e "$root_src" ]; then
            # /dev/root and the like: resolve through the mount's device number.
            majmin=$(findmnt -n -o MAJ:MIN / 2>/dev/null || true)
            if [ -n "$majmin" ] && [ -e "/sys/dev/block/$majmin" ]; then
                root_src="/dev/$(basename "$(readlink -f "/sys/dev/block/$majmin")")"
            fi
        fi
        [ -e "$root_src" ] \
            || die "cannot tell which disk holds the running root (${root_src}); refusing to guess"
        ;;
    *) root_src="" ;;
esac

# root_chain: every device under /; root_disks: the physical disks among them,
# which are also hidden from the listing below.
root_chain=""
root_disks=""
if [ -n "$root_src" ]; then
    chain=$(lsblk -nslo NAME,TYPE "$root_src") || die "cannot read the device chain under /"
    root_chain=$(printf '%s\n' "$chain" | awk '{print $1}' | sort -u | tr '\n' ' ')
    root_disks=$(printf '%s\n' "$chain" | awk '$2 == "disk" {print $1}' | sort -u | tr '\n' ' ')
fi

in_list() {
    local d
    for d in $2; do [ "$d" = "$1" ] && return 0; done
    return 1
}

# =============================================================================
# Step 3: Detect and select target device
# =============================================================================
echo ""
echo "--- Available block devices (excluding boot volume) ---"
echo ""

list_devices() {
    local found=0
    for dev in "$sysblock"/sd* "$sysblock"/nvme* "$sysblock"/vd* "$sysblock"/mmcblk*; do
        [ -e "$dev" ] || continue
        [ -e "$dev/partition" ] && continue
        devname=$(basename "$dev")

        # Hide the disks the running system lives on
        if in_list "$devname" "$root_disks"; then
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

if [ -n "$root_disks" ]; then
    echo ""
    echo "  (boot volume ${root_disks% } is hidden)"
fi
echo ""

read -p "Enter the target device path (e.g. /dev/sdX): " -r target_device 2>&1

[ -n "$target_device" ] || die "No device specified"

# Resolve aliases (/dev/disk/by-id/..., /dev/mapper/..., relative paths) to the
# kernel device, so every check below and dd itself see the same device.
target_device=$(readlink -f -- "$target_device") || die "cannot resolve ${target_device}"
target_name=$(basename "$target_device")

[ -e "$sysblock/$target_name" ] || die "${target_device} is not a block device"
if [ -e "$sysblock/$target_name/partition" ]; then
    die "${target_device} is a partition; give the whole disk - the image carries its own partition table"
fi
if in_list "$target_name" "$root_chain"; then
    die "${target_device} holds the running root filesystem -- refusing to overwrite"
fi

# =============================================================================
# Step 4: Safety checks
# =============================================================================

device_size_bytes=$(blockdev --getsize64 "$target_device" 2>/dev/null) || device_size_bytes=
case "$device_size_bytes" in
    '' | *[!0-9]*) die "cannot read the size of ${target_device}" ;;
esac
# A short target would lose its partition table to dd and then fail at the end
# of the device, leaving neither the old contents nor a bootable image.
if [ "$device_size_bytes" -lt "$image_bytes" ]; then
    die "${target_device} is smaller than the image (${device_size_bytes} < ${image_bytes} bytes)"
fi

device_size_gib=$(awk "BEGIN {printf \"%.2f\", $device_size_bytes / 1073741824}")
device_model=$(cat "$sysblock/${target_name}/device/model" 2>/dev/null | xargs || echo "unknown")
echo ""
echo "Target device: ${target_device}"
echo "  Model: ${device_model}"
echo "  Size:  ${device_size_gib} GiB"

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
# lsblk lists the target and its own partitions only; a name glob would also
# catch another disk sharing the prefix (/dev/sdb vs /dev/sdbb). A filesystem
# still mounted while dd rewrites its disk is corrupted, so a failure stops here.
echo ""
echo "Unmounting any mounted partitions on ${target_device}..."

mounted=$(lsblk -nlo PATH,MOUNTPOINT "$target_device" | awk 'NF >= 2 {print $1, $2}') \
    || die "cannot list the partitions of ${target_device}"
while read -r part mnt; do
    [ -n "$part" ] || continue
    if [ "$mnt" = "[SWAP]" ]; then
        echo "  Disabling swap on ${part}..."
        swapoff "$part" || die "cannot disable swap on ${part}"
    else
        # -A: every mount of the partition, not just the one lsblk shows.
        echo "  Unmounting ${part}..."
        umount -A "$part" || die "cannot unmount ${part}; close whatever holds it and retry"
    fi
done <<EOF
$mounted
EOF

# lsblk sees only this mount namespace. Inside the SDK container a partition
# the host has mounted looks free; the kernel still refuses to re-read the
# table of a disk with a partition in use, whoever uses it.
if ! rr_err=$(blockdev --rereadpt "$target_device" 2>&1); then
    case "$rr_err" in
        *busy*) die "${target_device} is still in use (mounted or held outside this environment, e.g. by the host); release it and retry" ;;
        *) echo "  warning: could not re-read the partition table of ${target_device}: ${rr_err}" ;;
    esac
fi

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
echo "The var partition grows to fill the rest of the disk on first boot."
