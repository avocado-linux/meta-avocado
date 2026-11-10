#!/usr/bin/env bash
#
# Phase 2a provisioning for rzv2n-sr-som: write the GPT OS image to eMMC via
# U-Boot's fastboot endpoint over USB-OTG. Requires the bootloader to already
# be in SPI NOR (run stone-provision-serial.sh first).

set -e
set -u
set -o pipefail

if [ "${AVOCADO_USB_PASSTHROUGH:-1}" != "1" ]; then
  cat >&2 <<EOF
ERROR: emmc provisioning requires USB device passthrough into the SDK so
fastboot can talk to U-Boot over USB-OTG. AVOCADO_USB_PASSTHROUGH=${AVOCADO_USB_PASSTHROUGH:-}
indicates the SDK was launched without USB access (likely Docker Desktop).
Run on a Linux host or expose the USB device to the container explicitly.
EOF
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DISK_IMAGE=$("${SCRIPT_DIR}/build-disk-image.sh")

cat <<EOF

================================================================
RZ/V2N SoM eMMC provisioning (Phase 2a: fastboot over USB-OTG)

Requires:
  1. The bootloader programmed to SPI NOR (the 'serial' profile).
  2. DIP S5 in SPI boot mode (MD0=OFF, MD1=ON).
  3. The SoC's USB2.0 ch0 (J5003) connected to this host.
  4. U-Boot running 'fastboot usb 0' (its fallback when neither eMMC nor
     SD boots; or stop autoboot and type it).
Disk image: $DISK_IMAGE
================================================================
EOF

if [ "${AVOCADO_RZ_BOARD_READY:-0}" != "1" ] && [ -t 0 ]; then
  echo "Press Enter to begin, or Ctrl-C to abort."
  read -r _
fi

echo "Waiting for fastboot device..."
for _ in $(seq 1 30); do
  if fastboot devices | grep -q .; then break; fi
  sleep 1
done
if ! fastboot devices | grep -q .; then
  echo "ERROR: no fastboot device detected. Is the OTG cable connected and the board in fastboot mode?" >&2
  exit 1
fi

echo "Fastboot device(s):"
fastboot devices
fastboot getvar product 2>&1 || true

# The whole disk image (GPT included) onto the eMMC user area. -S sends it
# as sparse chunks no larger than U-Boot's 1 GiB download buffer; unused
# space (the empty B slots) costs nothing on the wire.
FASTBOOT_TARGET="${AVOCADO_RZ_FASTBOOT_DISK:-mmc0}"
echo "=== Flashing ${DISK_IMAGE} to ${FASTBOOT_TARGET} ==="
fastboot -S 512M flash "$FASTBOOT_TARGET" "$DISK_IMAGE"

echo "=== Rebooting target ==="
fastboot reboot

cat <<EOF

================================================================
eMMC provisioning complete. The board should now boot from
eMMC: U-Boot's distro_bootcmd will probe mmc0, find
/extlinux/extlinux.conf on the boot-a partition, and load the
Avocado kernel.
================================================================
EOF
