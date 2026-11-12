#!/usr/bin/env bash
#
# Provisioning for stm32mp25-dk: write the assembled GPT disk image to an SD
# card via the host's USB SD reader. The DK boots from microSD when BOOT pins
# select SD; this provisioning produces a single image carrying FSBL + FIP +
# boot + rootfs + var.
#
# The SD card must already be inserted in the host USB reader before invoking.
# If no removable disk is detected the script exits immediately rather than
# blocking on insertion. Override auto-detection with AVOCADO_PROVISION_DEVICE=
# /dev/sdX (AVOCADO_SD_DEVICE is an alias); naming the card does not skip the
# retype, only AVOCADO_PROVISION_FORCE=1 does. AVOCADO_PROVISION_DRY_RUN=1 runs
# every guard and prints the write without doing it.

set -e
set -u
set -o pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

# Wrong-disk guards shared with the other sd and usb profiles. Shipped beside
# this script (the manifest lists it under provision.files).
# shellcheck source=/dev/null # sibling file, absent from a standalone lint
. "${SCRIPT_DIR}/avocado-safe-disk.sh"

# This profile honours a dry run (through the write choke point) but writes only
# the complete image, so a task other than complete is refused.
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

named=$(avocado_safe_disk_sd_device) || exit 1
if [ -n "$named" ]; then
  target="$named"
else
  # Choosing the target is an answer, and only a terminal answers.
  # AVOCADO_PROVISION_FORCE does not stand in for it.
  if [ ! -t 0 ]; then
    echo "ERROR: no device named and no terminal: cannot choose a target without a terminal." >&2
    echo "Set AVOCADO_PROVISION_DEVICE=/dev/sdX for an unattended run." >&2
    exit 1
  fi
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
      echo "Set AVOCADO_PROVISION_DEVICE=/dev/sdX to pick one, or unplug the others." >&2
      exit 1
      ;;
  esac
fi

# Whole disk on a USB or MMC bus that does not hold the running root. The
# kernel removable flag the listing above uses is not trusted for this.
avocado_safe_disk_check_device "$target" || exit 1
target="$AVOCADO_SAFE_DISK_DEV"

if command -v blockdev >/dev/null 2>&1; then
  size_bytes=$(blockdev --getsize64 "$target" 2>/dev/null || echo 0)
else
  sectors=$(cat "/sys/block/$(basename "$target")/size" 2>/dev/null || echo 0)
  size_bytes=$((sectors * 512))
fi
size_gib=$(awk "BEGIN { printf \"%.2f\", ${size_bytes} / (1024*1024*1024) }")

cat <<EOF

STM32MP25-DK SD provisioning
  Target: $target  (${size_gib} GiB)
  Image:  $(basename "$DISK_IMAGE")

WARNING: this will overwrite ALL data on $target.
EOF

# Typed retype of the device path, skipped only by AVOCADO_PROVISION_FORCE=1;
# naming the card does not skip it. A dry run asks nothing.
avocado_safe_disk_confirm "$target" || exit 1

target_base=$(basename "$target")
for partdir in /sys/block/"$target_base"/"$target_base"*; do
  [ -e "$partdir" ] || continue
  avocado_safe_disk_write umount "/dev/$(basename "$partdir")" 2>/dev/null || true
done

# Whatever is still mounted now was not unmounted above; never write under it.
avocado_safe_disk_unmounted "$target" || exit 1

echo "Writing $(basename "$DISK_IMAGE") to $target..."
avocado_safe_disk_write dd if="$DISK_IMAGE" of="$target" bs=4M oflag=direct status=progress
avocado_safe_disk_write sync

avocado_safe_disk_finish "$target"
if [ "${AVOCADO_PROVISION_DRY_RUN:-}" = "1" ]; then
  exit 0
fi

cat <<EOF

SD card written. Eject, insert into the DK, set BOOT pins to SD, power-cycle.
TF-A FSBL → FIP → OP-TEE → U-Boot → extlinux loads kernel + initramfs from
the boot-a partition.
EOF
