#!/usr/bin/env bash
#
# Phase 2b provisioning for rzv2n-sr-som: write the GPT OS image to an SD card
# via the host's USB SD reader. The SoM boots from SPI per Phase 1; this only
# populates the SD card with the Avocado kernel + rootfs + var.

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

================================================================
USB passthrough unavailable. Disk image written to:
  $AVOCADO_PROVISION_OUT/$(basename "$DISK_IMAGE")
Burn it to an SD card from your host OS, then insert into the SoM.
================================================================
EOF
    exit 0
fi

cat <<EOF

================================================================
RZ/V2N SoM SD card provisioning (Phase 2b)

Before continuing:
  1. The bootloader must already be in SPI NOR (Phase 1 'serial' profile).
  2. DIP S5 set to SPI boot (MD0=OFF, MD1=ON).
  3. Have an SD card and USB SD reader ready.

Press Enter to begin SD card detection, or Ctrl-C to abort.
================================================================
EOF
read -r _

# Snapshot block devices so we can identify the newly-inserted SD card.
mapfile -t before < <(lsblk -dpno NAME | grep -E '^/dev/sd[a-z]+$' || true)
echo "Existing block devices: ${before[*]:-none}"
echo
read -r -p "Insert your SD card into the host reader and press Enter..." _

echo "Watching for new block device (60 s timeout)..."
target=""
for _ in $(seq 1 60); do
    mapfile -t after < <(lsblk -dpno NAME | grep -E '^/dev/sd[a-z]+$' || true)
    for dev in "${after[@]}"; do
        if ! printf '%s\n' "${before[@]}" | grep -qx "$dev"; then
            target="$dev"
            break
        fi
    done
    [ -n "$target" ] && break
    sleep 1
done

if [ -z "$target" ]; then
    echo "ERROR: no new block device detected after 60 s." >&2
    exit 1
fi

# Wait for the kernel to fully enumerate the device.
for _ in $(seq 1 10); do
    if [ -b "$target" ] && timeout 2 dd if="$target" of=/dev/null bs=512 count=1 status=none 2>/dev/null; then
        break
    fi
    sleep 1
done

size_bytes=$(blockdev --getsize64 "$target" 2>/dev/null || echo 0)
size_gib=$(awk "BEGIN { printf \"%.2f\", ${size_bytes} / (1024*1024*1024) }")

cat <<EOF
Target detected:
  Device: $target
  Size:   ${size_gib} GiB

WARNING: this will overwrite ALL data on $target.
EOF
read -r -p "Type 'yes' to continue: " confirm
if [ "$confirm" != "yes" ]; then
    echo "Aborted by user."
    exit 1
fi

# Unmount any auto-mounted partitions on the target.
for p in $(lsblk -lnpo NAME "$target" | tail -n +2); do
    umount "$p" 2>/dev/null || true
done

echo "Writing $(basename "$DISK_IMAGE") to $target..."
dd if="$DISK_IMAGE" of="$target" bs=4M conv=fsync status=progress
sync

cat <<EOF

================================================================
SD card written. Eject the card, insert into the SoM, and power
on. With Phase 1 done, U-Boot's distro_bootcmd will probe mmc0
(eMMC), then mmc1 (SD), and boot the Avocado kernel from
/extlinux/extlinux.conf on the SD card's boot-a partition.
================================================================
EOF
