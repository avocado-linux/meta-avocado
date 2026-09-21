#!/usr/bin/env bash

set -e
set -u
set -o pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DISK_IMAGE=$("${SCRIPT_DIR}/build-disk-image.sh")

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
Burn it to a microSD with your host OS's disk imager, then insert into the
NanoPi R5S microSD slot and power-cycle.
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
            echo "ERROR: no removable disk detected. Insert the microSD via a USB reader and re-run." >&2
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

NanoPi R5S microSD provisioning
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

microSD written. Eject the card, insert into the NanoPi R5S, and power on.

The RK3568 BootROM prefers the microSD over eMMC, so a card written this way
takes precedence over whatever is already on the on-board eMMC. U-Boot's
distro_bootcmd probes mmc1 (the microSD slot -- rk3568.dtsi aliases mmc0 to
the eMMC sdhci and mmc1 to sdmmc0), finds /extlinux/extlinux.conf on boot-a,
and loads Image + DTB + initramfs.

Serial console: ttyS2 @ 1500000 baud, on the 3-pin debug header next to the
GPIO header (GND / TX / RX).
EOF
