#!/usr/bin/env bash
#
# Provisioning for stm32mp25-dk: write the assembled GPT disk image to an SD
# card via the host's USB SD reader. The DK boots from microSD when BOOT pins
# select SD; this provisioning produces a single image carrying FSBL + FIP +
# boot + rootfs + var.
#
# The SD card must already be inserted in the host USB reader before invoking.
# If no removable disk is detected the script exits immediately rather than
# blocking on insertion. Override auto-detection with AVOCADO_SD_DEVICE=/dev/sdX.

set -e
set -u
set -o pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DISK_IMAGE=$("${SCRIPT_DIR}/build-disk-image.sh")

# Docker Desktop / Windows / macOS path: produce the disk image and stop.
# The user burns it with their host OS's disk imager.
if [ "${AVOCADO_USB_PASSTHROUGH:-1}" = "0" ]; then
    if [ -z "${AVOCADO_PROVISION_OUT:-}" ]; then
        echo "ERROR: AVOCADO_PROVISION_OUT must be set when USB passthrough is unavailable." >&2
        exit 1
    fi
    mkdir -p "$AVOCADO_PROVISION_OUT"
    cp -v "$DISK_IMAGE" "$AVOCADO_PROVISION_OUT/"

    cat > "$AVOCADO_PROVISION_OUT/.provision-result.json" <<EOF
{
  "host_action": "burn_removable",
  "image": "$(basename "$DISK_IMAGE")"
}
EOF

    cat <<EOF

USB passthrough unavailable. Disk image written to:
  $AVOCADO_PROVISION_OUT/$(basename "$DISK_IMAGE")
Burn it to an SD card from your host OS, then insert into the DK.
EOF
    exit 0
fi

list_removable_disks() {
    if command -v lsblk >/dev/null 2>&1; then
        lsblk -dpno NAME,TYPE,RM 2>/dev/null \
            | awk '$2=="disk" && $3=="1" {print $1}'
    else
        local d
        for d in /sys/block/sd*; do
            [ -e "$d" ] || continue
            [ "$(cat "$d/removable" 2>/dev/null)" = "1" ] || continue
            echo "/dev/$(basename "$d")"
        done
    fi
}

if [ -n "${AVOCADO_SD_DEVICE:-}" ]; then
    target="$AVOCADO_SD_DEVICE"
    if [ ! -b "$target" ]; then
        echo "ERROR: AVOCADO_SD_DEVICE=$target is not a block device." >&2
        exit 1
    fi
else
    mapfile -t candidates < <(list_removable_disks)
    case ${#candidates[@]} in
        0)
            echo "ERROR: no removable disk detected. Insert your SD card via a USB reader and re-run." >&2
            exit 1
            ;;
        1)
            target="${candidates[0]}"
            ;;
        *)
            echo "ERROR: multiple removable disks detected:" >&2
            printf '  %s\n' "${candidates[@]}" >&2
            echo "Set AVOCADO_SD_DEVICE=/dev/sdX to pick one, or unplug the others." >&2
            exit 1
            ;;
    esac
fi

if command -v blockdev >/dev/null 2>&1; then
    size_bytes=$(blockdev --getsize64 "$target" 2>/dev/null || echo 0)
else
    sectors=$(cat "/sys/block/$(basename "$target")/size" 2>/dev/null || echo 0)
    size_bytes=$(( sectors * 512 ))
fi
size_gib=$(awk "BEGIN { printf \"%.2f\", ${size_bytes} / (1024*1024*1024) }")

cat <<EOF

STM32MP25-DK SD provisioning
  Target: $target  (${size_gib} GiB)
  Image:  $(basename "$DISK_IMAGE")

WARNING: this will overwrite ALL data on $target.
EOF
read -r -p "Continue? [y/N] " confirm
case "$confirm" in
    [yY]|[yY][eE][sS]) ;;
    *) echo "Aborted." ; exit 1 ;;
esac

target_base=$(basename "$target")
for partdir in /sys/block/"$target_base"/"$target_base"*; do
    [ -e "$partdir" ] || continue
    umount "/dev/$(basename "$partdir")" 2>/dev/null || true
done

echo "Writing $(basename "$DISK_IMAGE") to $target..."
dd if="$DISK_IMAGE" of="$target" bs=4M oflag=direct status=progress
sync

cat <<EOF

SD card written. Eject, insert into the DK, set BOOT pins to SD, power-cycle.
TF-A FSBL → FIP → OP-TEE → U-Boot → extlinux loads kernel + initramfs from
the boot-a partition.
EOF
