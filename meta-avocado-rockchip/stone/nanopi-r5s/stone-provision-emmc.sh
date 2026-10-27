#!/usr/bin/env bash
#
# emmc and sd-usb profiles for nanopi-r5s: build the GPT disk image, then write
# it with rkdeveloptool over the board's USB 3.0/MASK port, to the eMMC or
# (AVOCADO_ROCKUSB_STORAGE=sd, the sd-usb profile) to the microSD card.
#
# Two ways in, both 2207:350a and both listed as "Maskrom" by `rkdeveloptool ld`.
# Only a running loader answers `rid` (READ_FLASH_ID), so that tells them apart.
# Not `rfi`: U-Boot's rockusb doesn't implement READ_FLASH_INFO and the
# command never returns; the boot ROM doesn't answer either, hence the timeout.
#   - MaskROM: a blank or bricked board. The USB loader goes in first, then
#     `cs` picks the storage.
#   - U-Boot's rockusb: `rockusb 0 mmc 0` (eMMC) or
#     `rockusb 0 mmc 1` (microSD) at the U-Boot prompt has already picked it.
#     This is how a microSD that boots is rewritten: with a bootable card in,
#     the ROM boots it instead of falling through to MaskROM.
#
# Hardware prep (NanoPi R5S):
#   1. Connect the "USB 3.0/MASK" USB-A port (the corner one beside the microSD
#      slot) to this host with an A-to-A data cable. USB-C is power only.
#   2. Empty the microSD slot, or leave only a card with no bootloader on it.
#   3. Hold the MASK side button (it pulls eMMC D0 low), apply power, release
#      it about 3 s after the LED comes on. A board that already runs U-Boot
#      can also get there with `rbrom` at the U-Boot prompt.
#   4. `rkdeveloptool ld` shows a Maskrom device (2207:350a).
#   (or, from a running U-Boot: `rockusb 0 mmc <0|1>`)
#
# Flow:
#   - rkdeveloptool db <usb loader>: rkbin's DDR init + usbplug, packed by
#     rockchip-rkbin-usb-loader. It brings up the rockusb gadget that exposes
#     the eMMC. idbloader.img is not a loader and `db` rejects it.
#   - rkdeveloptool wl 0 <disk image>: the whole GPT image from LBA 0,
#     idbloader (LBA 64) and u-boot.itb (LBA 16384) included.
#   - rkdeveloptool rd: reset, so the board boots the eMMC.
#
# Unattended: no prompt. A test fixture enters MaskROM before calling this.

set -e
set -u
set -o pipefail

if [ "${AVOCADO_USB_PASSTHROUGH:-1}" != "1" ]; then
  cat >&2 <<EOF
ERROR: emmc provisioning requires USB device passthrough into the SDK so
rkdeveloptool can talk to the board's MaskROM over USB.
AVOCADO_USB_PASSTHROUGH=${AVOCADO_USB_PASSTHROUGH:-} indicates the SDK was
launched without USB access (likely Docker Desktop on macOS/Windows). Run
on a Linux host, or expose the USB device to the container explicitly.
EOF
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

LOADER_NAME=$(jq -r '.storage_devices.rootdisk.images.usb_loader // empty' "$AVOCADO_STONE_MANIFEST")
LOADER="${AVOCADO_STONE_DATA_DIR}/${LOADER_NAME:-rockchip-usb-loader.bin}"
if [ ! -f "$LOADER" ]; then
  echo "ERROR: USB loader not found: ${LOADER}" >&2
  echo "       rockchip-rkbin-usb-loader:do_deploy should have produced it." >&2
  exit 1
fi

DISK_IMAGE=$("${SCRIPT_DIR}/build-disk-image.sh")

echo "=== Waiting for a Maskrom device (hold MASK while powering on) ==="
for _ in $(seq 1 60); do
  rkdeveloptool ld 2>/dev/null | grep -q "Maskrom\|Loader" && break
  sleep 1
done
if ! rkdeveloptool ld 2>/dev/null | grep -q "Maskrom\|Loader"; then
  echo "ERROR: no rkdeveloptool device after 60 s." >&2
  echo "       Is the USB 3.0/MASK port connected, and was MASK held at power-on?" >&2
  exit 1
fi
rkdeveloptool ld

STORAGE="${AVOCADO_ROCKUSB_STORAGE:-emmc}"
case "$STORAGE" in
  emmc) STORAGE_CODE=1 ;;
  sd) STORAGE_CODE=2 ;;
  *) echo "ERROR: AVOCADO_ROCKUSB_STORAGE=$STORAGE (want emmc or sd)" >&2; exit 1 ;;
esac

if timeout 10 rkdeveloptool rid >/dev/null 2>&1; then
  echo "=== U-Boot rockusb: writing the device it exposes (expecting $STORAGE) ==="
else
  echo "=== Loading $(basename "$LOADER") ==="
  rkdeveloptool db "$LOADER"
  sleep 2
  rkdeveloptool cs "$STORAGE_CODE"
  rkdeveloptool rfi
fi

echo "=== Writing $(basename "$DISK_IMAGE") to $STORAGE LBA 0 ==="
rkdeveloptool wl 0 "$DISK_IMAGE"

# No `rl` readback: through the usbplug, reads past 32 MiB return 0xcc filler
# and then wedge the loader. The boot after `rd` is the check.

echo "=== Resetting the board ==="
rkdeveloptool rd

cat <<EOF

$STORAGE provisioning complete. The board now boots BootROM -> idbloader.img ->
u-boot.itb -> extlinux.conf in boot-a -> Image + DTB + initramfs -> rootfs-a.
A microSD card with a bootloader on it would win over the eMMC.
Serial console: ttyS2 at 1500000 on the 3-pin header beside the USB-C
(GND / TX / RX).
EOF
