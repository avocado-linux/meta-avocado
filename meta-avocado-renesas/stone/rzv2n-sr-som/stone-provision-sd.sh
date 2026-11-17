#!/usr/bin/env bash
#
# Phase 2b provisioning for rzv2n-sr-som: write the GPT OS image to an SD card
# via the host's USB SD reader. The SoM boots from SPI per Phase 1; this only
# populates the SD card with the Avocado kernel + rootfs + var.
#
# The SD card must already be inserted in the host USB reader before invoking.
# Name it with AVOCADO_PROVISION_DEVICE=/dev/sdX (AVOCADO_SD_DEVICE is an
# alias). With none named, the one disk on a USB or MMC bus is offered, and
# only on a terminal: an unattended run must name its device.
# AVOCADO_PROVISION_FORCE=1 skips the retype and never selects a disk.
# AVOCADO_PROVISION_DRY_RUN=1 runs every guard and prints the write without
# doing it.
# AVOCADO_RZ_SD_VIA_UMS=1 targets the card in the board, exposed by U-Boot's
# `ums 0 mmc 1`, found by its USB id instead of a named device.

set -e
set -u
set -o pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

# Wrong-disk guards shared with the other sd and usb profiles. Shipped beside
# this script (the manifest lists it under provision.files).
# shellcheck source=/dev/null # sibling file, absent from a standalone lint
. "${SCRIPT_DIR}/avocado-safe-disk.sh"
# shellcheck source=ums-disk.sh
. "${SCRIPT_DIR}/ums-disk.sh"

# A dry run goes through the write choke point; only the complete image is
# written, so a task other than complete is refused.
avocado_safe_disk_modes sd 1 0 || exit 1

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

sysblock=${AVOCADO_PROVISION_SYSBLOCK:-/sys/class/block}

named=""
if [ "${AVOCADO_RZ_SD_VIA_UMS:-0}" != "1" ]; then
  named=$(avocado_safe_disk_sd_device) || exit 1
fi
if [ "${AVOCADO_RZ_SD_VIA_UMS:-0}" = "1" ]; then
  # The card in the board, exposed by U-Boot's `ums 0 mmc 1` (a Rubicon's
  # provision hook starts it), rather than one in a USB card reader. Found by
  # its USB id, so no device is named and no terminal is needed to choose it;
  # the guards below still check what was found.
  echo "Waiting for the board's microSD as a USB disk ($AVOCADO_RZ_UMS_ID)..."
  target=$(wait_ums_disk 60) || exit 1
elif [ -n "$named" ]; then
  target="$named"
else
  # Choosing the target is an answer, and only a terminal answers.
  # AVOCADO_PROVISION_FORCE does not stand in for it.
  if [ ! -t 0 ]; then
    echo "ERROR: no device named and no terminal: cannot choose a target without a terminal." >&2
    echo "Set AVOCADO_PROVISION_DEVICE=/dev/sdX for an unattended run." >&2
    exit 1
  fi
  mapfile -t candidates < <(avocado_safe_disk_bus_candidates)
  case ${#candidates[@]} in
    0)
      echo "ERROR: no disk on a USB or MMC bus detected. Insert your SD card via a USB reader and re-run." >&2
      exit 1
      ;;
    1)
      target="${candidates[0]}"
      ;;
    *)
      echo "ERROR: multiple disks on a USB or MMC bus detected:" >&2
      printf '  %s\n' "${candidates[@]}" >&2
      echo "Set AVOCADO_PROVISION_DEVICE=/dev/sdX to pick one, or unplug the others." >&2
      exit 1
      ;;
  esac
fi

# Whole disk on a USB or MMC bus that does not hold the running root.
avocado_safe_disk_check_device "$target" || exit 1
target="$AVOCADO_SAFE_DISK_DEV"

# An image larger than the disk is refused before the retype and before any
# write, not after dd has overwritten the card's partition table.
avocado_safe_disk_image_fits "$DISK_IMAGE" "$target" || exit 1

cat <<EOF

RZ/V2N SoM SD provisioning
  Image:  $(basename "$DISK_IMAGE")
EOF

# Typed retype of the device path, skipped only by AVOCADO_PROVISION_FORCE=1;
# naming the card does not skip it. A dry run asks nothing.
# BOARD_READY skips the question only for the board's own UMS gadget, found by
# its USB id; a disk picked on the host (named, or the bus scan) could be any
# card or stick, so it is always confirmed.
if [ "${AVOCADO_RZ_SD_VIA_UMS:-0}" != "1" ] || [ "${AVOCADO_RZ_BOARD_READY:-0}" != "1" ]; then
  avocado_safe_disk_confirm "$target" || exit 1
fi

target_base=$(basename "$target")
for partdir in "$sysblock/$target_base/$target_base"*; do
  [ -e "$partdir" ] || continue
  avocado_safe_disk_write umount "${AVOCADO_SAFE_DISK_DEVDIR:-/dev}/$(basename "$partdir")" 2>/dev/null || true
done

# Whatever is still mounted now was not unmounted above; never write under it.
avocado_safe_disk_unmounted "$target" || exit 1

echo "Writing $(basename "$DISK_IMAGE") to $target..."
# oflag=direct bypasses the page cache so the dd progress meter reflects real
# device throughput (typically 15-30 MB/s on a USB SD reader, not the 2-3 GB/s
# RAM-to-RAM copy speed). With buffered I/O dd "finishes" fast and the script
# appeared to hang for minutes inside sync; with direct I/O the wait is upfront
# and visible.
avocado_safe_disk_write dd if="$DISK_IMAGE" of="$target" bs=4M oflag=direct status=progress
avocado_safe_disk_write sync
# The board is power-cycled right after: flush the device's own buffers too.
avocado_safe_disk_write blockdev --flushbufs "$target" || true

avocado_safe_disk_finish "$target"
if [ "${AVOCADO_PROVISION_DRY_RUN:-}" = "1" ]; then
  exit 0
fi

cat <<EOF

SD card written. Insert it into the SoM (or stop 'ums' if it was written
in the board) and power-cycle. U-Boot boots the microSD's slot A when the
eMMC carries no OS; with an OS on the eMMC, the eMMC boots.
EOF
