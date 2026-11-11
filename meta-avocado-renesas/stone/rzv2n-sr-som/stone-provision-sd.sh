#!/usr/bin/env bash
#
# Phase 2b provisioning for rzv2n-sr-som: write the GPT OS image to an SD card
# via the host's USB SD reader. The SoM boots from SPI per Phase 1; this only
# populates the SD card with the Avocado kernel + rootfs + var.
#
# The SD card must already be inserted in the host USB reader before invoking.
# If no removable disk is detected the script exits immediately rather than
# blocking on insertion. Override auto-detection with AVOCADO_SD_DEVICE=/dev/sdX.

set -e
set -u
set -o pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=ums-disk.sh
. "${SCRIPT_DIR}/ums-disk.sh"
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

  cat >"$AVOCADO_PROVISION_OUT/.provision-result.json" <<EOF
{
  "host_action": "burn_removable",
  "image": "$(basename "$DISK_IMAGE")"
}
EOF

  cat <<EOF

USB passthrough unavailable. Disk image written to:
  $AVOCADO_PROVISION_OUT/$(basename "$DISK_IMAGE")
Burn it to an SD card from your host OS, then insert into the SoM.
EOF
  exit 0
fi

# Enumerate removable USB-attached disks. lsblk is preferred (handles SD vs
# eMMC vs internal disks correctly). /sys/block is the fallback when the SDK
# doesn't ship util-linux-lsblk.
list_removable_disks() {
  if command -v lsblk >/dev/null 2>&1; then
    # NAME (path), TYPE, RM (removable). Match disks marked removable.
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

if [ "${AVOCADO_RZ_SD_VIA_UMS:-0}" = "1" ]; then
  # The card in the board, exposed by U-Boot's `ums 0 mmc 1` (a Rubicon's
  # provision hook starts it), rather than one in a USB card reader.
  echo "Waiting for the board's microSD as a USB disk ($AVOCADO_RZ_UMS_ID)..."
  target=$(wait_ums_disk 60)
elif [ -n "${AVOCADO_SD_DEVICE:-}" ]; then
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

# Size for the y/N confirmation, via blockdev (preferred) or sysfs.
if command -v blockdev >/dev/null 2>&1; then
  size_bytes=$(blockdev --getsize64 "$target" 2>/dev/null || echo 0)
else
  sectors=$(cat "/sys/block/$(basename "$target")/size" 2>/dev/null || echo 0)
  size_bytes=$((sectors * 512))
fi
size_gib=$(awk "BEGIN { printf \"%.2f\", ${size_bytes} / (1024*1024*1024) }")

cat <<EOF

RZ/V2N SoM SD provisioning
  Target: $target  (${size_gib} GiB)
  Image:  $(basename "$DISK_IMAGE")

WARNING: this will overwrite ALL data on $target.
EOF
# BOARD_READY skips the question only for the board's own UMS gadget, found by
# its USB id; a disk picked on the host (AVOCADO_SD_DEVICE, the removable-disk
# scan) could be any card or stick, so it is always confirmed.
if [ "${AVOCADO_RZ_SD_VIA_UMS:-0}" != "1" ] || [ "${AVOCADO_RZ_BOARD_READY:-0}" != "1" ]; then
  read -r -p "Continue? [y/N] " confirm
  case "$confirm" in
    [yY] | [yY][eE][sS]) ;;
    *)
      echo "Aborted."
      exit 1
      ;;
  esac
fi

# Unmount any auto-mounted partitions before writing.
write_disk_image "$DISK_IMAGE" "$target"

cat <<EOF

SD card written. Insert it into the SoM (or stop 'ums' if it was written
in the board) and power-cycle. U-Boot boots the microSD's slot A when the
eMMC carries no OS; with an OS on the eMMC, the eMMC boots.
EOF
