#!/usr/bin/env bash
#
# sd-usb profile for nanopi-r5s: build the GPT disk image and write it to the
# microSD through U-Boot's USB mass-storage gadget on the USB 3.0/MASK port.
#
# Hardware prep: a U-Boot on the eMMC or the card; at its prompt,
# `ums 0 mmc 1` (microSD; `mmc 0` would be the eMMC). The board then shows up
# as 2207:0010 with one disk, vendor "Linux", model "UMS disk 0".
#
# U-Boot's rockusb would be the rkdeveloptool route, but its write stalls on
# this board ("request ... was not queued to ep1in-bulk"), with or without a
# USB/IP hop; UMS writes the same image cleanly.
#
# Environment:
#   AVOCADO_PROVISION_FORCE=1    skip the retype confirmation (guards still run)
#   AVOCADO_PROVISION_DRY_RUN=1  run every guard on the exported disk and print
#                                the dd instead of running it
#   AVOCADO_PROVISION_FWUP_TASK  complete only; a dd writes the whole image
#   SYSFS                        sysfs root the wait scans (default /sys)

set -e
set -u
set -o pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# Wrong-disk guards and the one place that escalates to root, shipped beside
# this script through the manifest's provision.files.
# shellcheck source=/dev/null
. "${SCRIPT_DIR}/avocado-safe-disk.sh"

# The operator starts the export at the U-Boot prompt, not this script, so a dry
# run sees the real disk without changing the board and can run every guard.
avocado_safe_disk_modes sd-usb 1 0 || exit 1

if [ "${AVOCADO_USB_PASSTHROUGH:-1}" != "1" ]; then
  echo "ERROR: sd-usb provisioning needs the board's USB disk inside the SDK." >&2
  exit 1
fi

DISK_IMAGE=$("${SCRIPT_DIR}/build-disk-image.sh")

ums_disk() {
  local d
  for d in "${SYSFS:-/sys}"/block/sd*; do
    [ -e "$d/device/model" ] || continue
    if [ "$(tr -d ' ' <"$d/device/vendor")" = "Linux" ] \
      && [ "$(sed 's/ *$//' "$d/device/model")" = "UMS disk 0" ]; then
      echo "${AVOCADO_SAFE_DISK_DEVDIR:-/dev}/${d##*/}"
      return 0
    fi
  done
  return 1
}

echo "=== Waiting for U-Boot's UMS disk (ums 0 mmc 1 at the U-Boot prompt) ==="
DEV=""
for _ in $(seq 1 60); do
  DEV=$(ums_disk) && break
  sleep 1
done
if [ -z "$DEV" ]; then
  echo "ERROR: no 'Linux UMS disk 0' block device after 60 s." >&2
  exit 1
fi
echo "UMS disk: $DEV"

# The vendor and model strings only say what the disk claims to be. Nothing is
# shown for confirmation or written until it is a whole USB or MMC disk that
# does not hold the running root.
avocado_safe_disk_check_device "$DEV" || exit 1
DEV=$AVOCADO_SAFE_DISK_DEV

# The disk was found, not named, so the operator retypes its path; only
# AVOCADO_PROVISION_FORCE=1 skips that.
avocado_safe_disk_confirm "$DEV" 0 || exit 1

# A desktop may auto-mount the card's partitions the moment the export appears.
# Release what is mounted here, then refuse whatever is still mounted or in use,
# here or in the host table avocado-cli exports.
for part in $(mount | awk -v d="$DEV" '$1 == d || (index($1, d) == 1 && substr($1, length(d) + 1) ~ /^[0-9]+$/) { print $1 }' | sort -u); do
  echo "Unmounting ${part}..."
  avocado_safe_disk_write umount "$part" || {
    echo "ERROR: failed to unmount ${part}" >&2
    exit 1
  }
done
avocado_safe_disk_unmounted "$DEV" || exit 1

echo "=== Writing $(basename "$DISK_IMAGE") to $DEV ==="
avocado_safe_disk_write dd if="$DISK_IMAGE" of="$DEV" bs=4M oflag=direct conv=fsync || exit 1

if [ "${AVOCADO_PROVISION_DRY_RUN:-}" = "1" ]; then
  avocado_safe_disk_finish "$DEV"
  exit 0
fi
sync

cat <<EOT

microSD provisioning complete. The boot ROM prefers the eMMC when both carry
a bootloader; to boot the card with the eMMC populated, hold MASK at power-on.
EOT
