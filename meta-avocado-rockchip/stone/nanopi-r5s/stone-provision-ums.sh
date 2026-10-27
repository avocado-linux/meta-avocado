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

set -e
set -u
set -o pipefail

if [ "${AVOCADO_USB_PASSTHROUGH:-1}" != "1" ]; then
  echo "ERROR: sd-usb provisioning needs the board's USB disk inside the SDK." >&2
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DISK_IMAGE=$("${SCRIPT_DIR}/build-disk-image.sh")

ums_disk() {
  local d
  for d in /sys/block/sd*; do
    [ -e "$d/device/model" ] || continue
    if [ "$(tr -d ' ' <"$d/device/vendor")" = "Linux" ] &&
      [ "$(sed 's/ *$//' "$d/device/model")" = "UMS disk 0" ]; then
      echo "/dev/${d##*/}"
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
echo "UMS disk: $DEV ($(($(cat "/sys/block/${DEV#/dev/}/size") / 2048)) MiB)"

echo "=== Writing $(basename "$DISK_IMAGE") to $DEV ==="
dd if="$DISK_IMAGE" of="$DEV" bs=4M oflag=direct conv=fsync
sync

cat <<EOT

microSD provisioning complete. The boot ROM prefers the eMMC when both carry
a bootloader; to boot the card with the eMMC populated, hold MASK at power-on.
EOT
