#!/usr/bin/env bash
#
# Provisioning for stm32mp25-dk: bootstrap onboard eMMC via the stm32mp2 ROM's
# USB-DFU download mode. Use this when you don't have a working SD card or
# bootloader on the eMMC yet.
#
# The ROM exposes DFU when BOOT pins are set to "USB boot" / "no flash":
#   BOOT0=0, BOOT1=0, BOOT2=1 on stm32mp257f-dk (verify against your board's
#   silkscreen — DIP positions vary by revision).
#
# This profile relies on dfu-util, which is shipped via nativesdk-dfu-util
# in the avocado-sdk-target bbappend. ST's STM32CubeProgrammer CLI is the
# vendor-recommended flasher but its license precludes redistribution; if a
# user has it locally installed they can override AVOCADO_STM32_FLASHER.

set -e
set -u
set -o pipefail

if [ "${AVOCADO_USB_PASSTHROUGH:-1}" != "1" ]; then
    cat >&2 <<EOF
ERROR: serial provisioning requires USB device passthrough into the SDK so
the host can talk to the stm32mp2 ROM over USB-DFU. AVOCADO_USB_PASSTHROUGH=${AVOCADO_USB_PASSTHROUGH:-}
indicates the SDK was launched without USB access (likely Docker Desktop).
Run on a Linux host or expose the USB device to the container explicitly.
EOF
    exit 1
fi

MANIFEST="$AVOCADO_STONE_MANIFEST"
DATA_DIR="$AVOCADO_STONE_DATA_DIR"

FSBL=$(jq -r '.storage_devices.rootdisk.images.fsbl' "$MANIFEST")
FIP=$(jq -r '.storage_devices.rootdisk.images.fip' "$MANIFEST")

for f in "$FSBL" "$FIP"; do
    if [ ! -f "${DATA_DIR}/${f}" ]; then
        echo "ERROR: missing artifact ${DATA_DIR}/${f}" >&2
        exit 1
    fi
done

# stm32mp2 USB-DFU VID:PID — the ROM enumerates as 0483:df11 (STMicroelectronics
# DfuSe) just like older stm32mp1 silicon. dfu-util addresses partitions by
# alt-setting; alt 0 is FSBL, alt 1 is FIP for the SoC's "boot from USB" flow.
DFU_VID_PID="${AVOCADO_STM32_DFU_VID_PID:-0483:df11}"

cat <<EOF

================================================================
STM32MP25-DK bootloader provisioning (USB-DFU)

Before continuing, confirm:
  1. BOOT pins are set to USB-DFU mode (per the DK silkscreen).
  2. USB-OTG cable (CN3) is connected from the DK to this host.
  3. The board is powered on; the ROM has enumerated as ${DFU_VID_PID}.

Press Enter to start flashing, or Ctrl-C to abort.
================================================================
EOF
read -r _

echo "Waiting for stm32mp2 USB-DFU device (${DFU_VID_PID})..."
for _ in $(seq 1 30); do
    if dfu-util -l 2>/dev/null | grep -q "${DFU_VID_PID}"; then break; fi
    sleep 1
done
if ! dfu-util -l 2>/dev/null | grep -q "${DFU_VID_PID}"; then
    echo "ERROR: no DFU device found at ${DFU_VID_PID}. Check BOOT pins and USB cable." >&2
    exit 1
fi

echo "=== Downloading FSBL via DFU alt 0 ==="
dfu-util -d "${DFU_VID_PID}" -a 0 -D "${DATA_DIR}/${FSBL}"

echo "=== Downloading FIP via DFU alt 1 ==="
dfu-util -d "${DFU_VID_PID}" -a 1 -D "${DATA_DIR}/${FIP}"

cat <<EOF

================================================================
DFU bootloader download complete.

The board has FSBL+FIP loaded into RAM and U-Boot will start.
Next steps:
  1. With U-Boot running, run 'stone-provision-emmc.sh' (or
     'stone-provision-sd.sh') to install the OS image.
  2. After the OS is on persistent storage, set BOOT pins to
     match (eMMC or SD), then power-cycle.
================================================================
EOF
