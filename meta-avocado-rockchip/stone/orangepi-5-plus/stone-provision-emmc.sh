#!/usr/bin/env bash
#
# emmc profile for orangepi-5-plus: build the GPT disk image, then write it
# to the on-board eMMC via rkdeveloptool over USB-C OTG.
#
# Hardware prep (Orange Pi 5 Plus):
#   1. Power the board OFF.
#   2. Connect the USB-C OTG cable from the BOTTOM USB-C port (the one closer
#      to the power button) to this host.
#   3. Hold the MaskROM button (small button on the underside of the board).
#   4. While holding MaskROM, briefly press Reset (or apply power). Release
#      MaskROM after ~3 seconds.
#   5. Verify with `rkdeveloptool ld` -- should show "Maskrom" device.
#
# Flow:
#   - rkdeveloptool db idbloader.img : upload our idbloader to RAM, which
#     initialises DDR and brings up the rockusb storage gadget exposing the
#     on-board eMMC as a mass-storage endpoint to this host.
#   - rkdeveloptool wl 0 <disk-image>: write the assembled GPT disk image to
#     LBA 0 of the eMMC (overwrites everything, including any existing
#     bootloader at LBA 64 / u-boot.itb at LBA 16384, both of which are
#     embedded in our disk image at the same offsets).
#   - rkdeveloptool rd : reset the target so it reboots from the freshly
#     populated eMMC.

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
Orange Pi 5 Plus eMMC provisioning (rkdeveloptool over USB-C OTG)

Before continuing, confirm:
  1. The USB-C OTG cable is connected (bottom USB-C port near power button).
  2. The board has been booted into MaskROM mode (hold MaskROM button while
     powering on / pressing reset).
  3. \`rkdeveloptool ld\` shows a Maskrom device on this host.

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

Serial console: ttyS2 @ 1500000 baud (UART2 on the GPIO header).
================================================================
EOF
