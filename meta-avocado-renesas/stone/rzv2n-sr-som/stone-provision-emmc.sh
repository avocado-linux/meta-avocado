#!/usr/bin/env bash
#
# Phase 2a provisioning for rzv2n-sr-som: write the GPT OS image to the eMMC,
# exposed as a USB disk by U-Boot's `ums 0 mmc 0` on the SoC's USB2.0 ch0
# (J5003). Requires the bootloader in SPI NOR (the serial profile first).
#
# Inputs (env vars):
#   AVOCADO_USB_PASSTHROUGH  - "1" when the host's USB disks reach the SDK
#   AVOCADO_RZ_BOARD_READY   - "1" when automation already started `ums`
#                              (a Rubicon's provision hook): no prompt
#   AVOCADO_RZ_UMS_ID        - the gadget's USB id (default 18d1:0d02)

set -e
set -u
set -o pipefail

if [ "${AVOCADO_USB_PASSTHROUGH:-1}" != "1" ]; then
  cat >&2 <<EOF
ERROR: emmc provisioning requires USB device passthrough into the SDK, to
write the board's eMMC as a USB disk. AVOCADO_USB_PASSTHROUGH=${AVOCADO_USB_PASSTHROUGH:-}
indicates the SDK was launched without USB access (likely Docker Desktop).
Run on a Linux host or expose the USB device to the container explicitly.
EOF
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=ums-disk.sh
. "${SCRIPT_DIR}/ums-disk.sh"
DISK_IMAGE=$("${SCRIPT_DIR}/build-disk-image.sh")

cat <<EOF

================================================================
RZ/V2N SoM eMMC provisioning (Phase 2a: U-Boot USB mass storage)

Requires:
  1. The bootloader programmed to SPI NOR (the 'serial' profile).
  2. DIP S5 in SPI boot mode (MD0=OFF, MD1=ON).
  3. The SoC's USB2.0 ch0 (J5003) connected to this host.
  4. In U-Boot (stop autoboot on the console): ums 0 mmc 0
Disk image: $DISK_IMAGE
================================================================
EOF

if [ "${AVOCADO_RZ_BOARD_READY:-0}" != "1" ] && [ -t 0 ]; then
  echo "Press Enter once 'ums 0 mmc 0' is running, or Ctrl-C to abort."
  read -r _
fi

echo "Waiting for the board's eMMC as a USB disk ($AVOCADO_RZ_UMS_ID)..."
TARGET=$(wait_ums_disk 60)
write_disk_image "$DISK_IMAGE" "$TARGET"

cat <<EOF

================================================================
eMMC provisioning complete. Stop 'ums' (Ctrl-C on the console) or
power-cycle: U-Boot's distro_bootcmd probes mmc0 (eMMC) first and
boots /extlinux/extlinux.conf from boot-a.
================================================================
EOF
