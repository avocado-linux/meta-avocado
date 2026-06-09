#!/usr/bin/env bash
#
# Phase 1 provisioning for rzv2n-sr-som: program SPI NOR with BL2 + FIP via the
# on-target Flash Writer over SCIF UART. The board must be in Serial Downloader
# mode (DIP S5: MD0=ON, MD1=ON) before this runs.
#
# Inputs (env vars from avocado/stone):
#   AVOCADO_STONE_MANIFEST   - manifest JSON path
#   AVOCADO_STONE_DATA_DIR   - directory containing BL2/FIP/Flash_Writer.mot
#   AVOCADO_USB_PASSTHROUGH  - "1" when /dev/ttyUSB* is reachable from the SDK

set -e
set -u
set -o pipefail

if [ "${AVOCADO_USB_PASSTHROUGH:-1}" != "1" ]; then
    cat >&2 <<EOF
ERROR: serial provisioning requires USB-UART passthrough into the SDK
container. AVOCADO_USB_PASSTHROUGH=${AVOCADO_USB_PASSTHROUGH:-} indicates
the SDK was launched without /dev/ttyUSB* access (likely Docker Desktop on
macOS/Windows). Run avocado provision on a Linux host or expose the UART
device explicitly.
EOF
    exit 1
fi

MANIFEST="$AVOCADO_STONE_MANIFEST"
DATA_DIR="$AVOCADO_STONE_DATA_DIR"

BL2=$(jq -r '.storage_devices.rootdisk.images.bl2_spi' "$MANIFEST")
FIP=$(jq -r '.storage_devices.rootdisk.images.fip' "$MANIFEST")
FW=$(jq -r '.storage_devices.rootdisk.images.flash_writer' "$MANIFEST")

for f in "$BL2" "$FIP" "$FW"; do
    if [ ! -f "${DATA_DIR}/${f}" ]; then
        echo "ERROR: missing artifact ${DATA_DIR}/${f}" >&2
        exit 1
    fi
done

PORT="${AVOCADO_RZ_SERIAL_PORT:-/dev/ttyUSB0}"
SPEED="${AVOCADO_RZ_SERIAL_SPEED:-921600}"

if [ ! -e "$PORT" ]; then
    echo "ERROR: serial port $PORT not present in the SDK container." >&2
    echo "Set AVOCADO_RZ_SERIAL_PORT to the correct /dev/ttyUSB* node." >&2
    exit 1
fi

cat <<EOF

================================================================
RZ/V2N SoM bootloader provisioning (Phase 1: SPI NOR via SCIF)

Before continuing, confirm:
  1. DIP S5 is set to Serial Downloader mode (MD0=ON, MD1=ON).
  2. The USB-to-UART adapter is wired to the SoM's debug SCIF.
  3. The SoM is powered on.

Detected serial port: $PORT (override with AVOCADO_RZ_SERIAL_PORT)
Transfer speed:       $SPEED baud (override with AVOCADO_RZ_SERIAL_SPEED)

Press Enter to start flashing, or Ctrl-C to abort.
================================================================
EOF
read -r _

rz-flash-writer-tool \
    --target spi \
    --fw    "${DATA_DIR}/${FW}" \
    --bl2   "${DATA_DIR}/${BL2}" \
    --fip   "${DATA_DIR}/${FIP}" \
    --port  "$PORT" \
    --speed "$SPEED"

cat <<EOF

================================================================
SPI NOR programming complete.

Next steps:
  1. Power off the SoM.
  2. Set DIP S5 to SPI boot mode (MD0=OFF, MD1=ON).
  3. Power on. BL2 will load from SPI, FIP will follow, U-Boot will run.
  4. With no OS image present, U-Boot enters fastboot. Run
     'avocado provision emmc' (or 'avocado provision sd') to install the OS.
================================================================
EOF
