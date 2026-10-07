#!/usr/bin/env bash

set -e
set -u
set -o pipefail

if [ "${AVOCADO_USB_PASSTHROUGH:-1}" != "1" ]; then
  cat >&2 <<EOF
ERROR: emmc provisioning requires USB device passthrough into the SDK so
rkdeveloptool can talk to the board over USB-C OTG.
AVOCADO_USB_PASSTHROUGH=${AVOCADO_USB_PASSTHROUGH:-} indicates the SDK was
launched without USB access (likely Docker Desktop on macOS/Windows). Run
on a Linux host, or expose the USB device to the container explicitly.
EOF
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DISK_IMAGE=$("${SCRIPT_DIR}/build-disk-image.sh")

LOADER="${AVOCADO_STONE_DATA_DIR}/idbloader.img"
if [ ! -f "$LOADER" ]; then
  echo "ERROR: idbloader.img not found in ${AVOCADO_STONE_DATA_DIR}." >&2
  echo "       u-boot:do_deploy should have produced it. Check the build." >&2
  exit 1
fi

cat <<EOF

================================================================
NanoPi R5S eMMC provisioning (rkdeveloptool over USB-C OTG)

Before continuing, confirm:
  1. No microSD card is inserted (the BootROM would prefer it over eMMC).
  2. The USB-C cable is connected between the board's USB-C port and this
     host -- it supplies both power and the rockusb data link.
  3. The board was brought up in MaskROM mode (hold the MASK button beside
     the USB-C port while applying power).
  4. \`rkdeveloptool ld\` shows a Maskrom device on this host.

Press Enter to begin, or Ctrl-C to abort.
================================================================
EOF
read -r _

echo "=== Waiting for Maskrom device ==="
for _ in $(seq 1 30); do
  if rkdeveloptool ld 2>/dev/null | grep -qi "Maskrom\|Loader"; then
    break
  fi
  sleep 1
done
if ! rkdeveloptool ld 2>/dev/null | grep -qi "Maskrom\|Loader"; then
  echo "ERROR: no rkdeveloptool device detected after 30s." >&2
  echo "       Is the OTG cable connected? Was MaskROM held during reset?" >&2
  rkdeveloptool ld >&2 || true
  exit 1
fi

echo "rkdeveloptool device(s):"
rkdeveloptool ld

echo "=== Uploading idbloader to bring up rockusb storage gadget ==="
rkdeveloptool db "$LOADER"
sleep 2

echo "=== Writing disk image to eMMC LBA 0 ==="
rkdeveloptool wl 0 "$DISK_IMAGE"

echo "=== Resetting target ==="
rkdeveloptool rd

cat <<EOF

================================================================
eMMC provisioning complete. The board should reboot from eMMC:
BootROM -> idbloader.img (LBA 64) -> u-boot.itb (LBA 16384) ->
extlinux.conf in boot-a -> Image + DTB + initramfs ->
rootfs-a (erofs).

Keep the microSD slot empty on the next boot, otherwise the BootROM will
prefer the card over the eMMC you just wrote.

Serial console: ttyS2 @ 1500000 baud, on the 3-pin debug header next to the
GPIO header (GND / TX / RX).
================================================================
EOF
