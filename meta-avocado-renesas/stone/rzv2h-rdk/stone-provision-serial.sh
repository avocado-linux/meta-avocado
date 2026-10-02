#!/usr/bin/env bash
#
# Phase 1 provisioning for avocado-rzv2h-rdk: program xSPI NOR with BL2 + FIP via
# the on-target Flash Writer over SCIF UART. The board must be in Serial
# Downloader mode before this runs.
#
# The RDK's boot-mode switch positions are not confirmed here. The rzv2n SoM uses
# DIP S5 MD0=ON/MD1=ON for Serial Downloader and MD0=OFF/MD1=ON for SPI boot; the
# RDK is a different board and its switch is a different part, so read the RDK
# hardware manual (R16UH0052EU0100) rather than trusting the SoM values.
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
RZ/V2H RDK bootloader provisioning (Phase 1: xSPI NOR via SCIF)

Before continuing, confirm:
  1. The boot-mode switch is set to Serial Downloader mode. Positions are
     board-specific and unconfirmed for the RDK; see the RDK hardware
     manual R16UH0052EU0100.
  2. The USB-UART (Micro-B, FT234XD) is connected to the host.
  3. The board is powered on.

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
xSPI NOR programming complete.

Next steps:
  1. Power off the board.
  2. Set the boot-mode switch to xSPI boot (see the RDK hardware manual).
  3. Power on. BL2 will load from xSPI, FIP will follow, U-Boot will run.
  4. With no OS image on the card, the boot command finds no extlinux.conf
     and drops to the U-Boot prompt. This board has no fastboot and no
     eMMC; run 'avocado provision sd' to write the OS to a microSD card.
================================================================
EOF
