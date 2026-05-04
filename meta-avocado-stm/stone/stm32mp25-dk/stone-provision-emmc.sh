#!/usr/bin/env bash
#
# Provisioning for stm32mp25-dk: write the assembled GPT OS image to onboard
# eMMC via U-Boot fastboot over USB-OTG. Requires the bootloader to already
# be on the boot media (run stone-provision-serial.sh first to seed eMMC's
# boot area, or boot once from SD).

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
STM32MP25-DK eMMC provisioning (fastboot over USB-OTG)

Before continuing, confirm:
  1. The bootloader has been programmed to a boot medium the ROM can use
     (either run stone-provision-serial.sh to seed eMMC's boot partition,
      or boot once from an SD card produced by stone-provision-sd.sh).
  2. The DK USB-OTG port (CN3) is connected to this host.
  3. The board is powered on; U-Boot has entered fastboot mode (no OS
     image present in eMMC, or the user dropped to U-Boot prompt and ran
     'fastboot usb 0').

Press Enter to begin, or Ctrl-C to abort.
================================================================
EOF
read -r _

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

echo "=== Flashing GPT ==="
fastboot flash gpt "$DISK_IMAGE"

NUM_PARTITIONS=$(jq '.storage_devices.rootdisk.partitions | length' "$AVOCADO_STONE_MANIFEST")
for i in $(seq 0 $(( NUM_PARTITIONS - 1 ))); do
    name=$(jq -r ".storage_devices.rootdisk.partitions[$i].name" "$AVOCADO_STONE_MANIFEST")
    img_key=$(jq -r ".storage_devices.rootdisk.partitions[$i].image // \"\"" "$AVOCADO_STONE_MANIFEST")
    [ -z "$img_key" ] && continue

    build_type=$(jq -r ".storage_devices.rootdisk.images.\"${img_key}\" | if type == \"object\" then .build_args.type // \"\" else \"\" end" "$AVOCADO_STONE_MANIFEST")
    if [ "$build_type" = "fat" ]; then
        out=$(jq -r ".storage_devices.rootdisk.images.\"${img_key}\".out" "$AVOCADO_STONE_MANIFEST")
        src="${AVOCADO_STONE_BUILD_DIR}/${out}"
    else
        type=$(jq -r ".storage_devices.rootdisk.images.\"${img_key}\" | type" "$AVOCADO_STONE_MANIFEST")
        if [ "$type" = "string" ]; then
            f=$(jq -r ".storage_devices.rootdisk.images.\"${img_key}\"" "$AVOCADO_STONE_MANIFEST")
        else
            f=$(jq -r ".storage_devices.rootdisk.images.\"${img_key}\".out" "$AVOCADO_STONE_MANIFEST")
        fi
        src="${AVOCADO_STONE_DATA_DIR}/${f}"
    fi

    echo "=== Flashing ${name} from ${src} ==="
    fastboot flash "$name" "$src"
done

echo "=== Rebooting target ==="
fastboot reboot

cat <<EOF

================================================================
eMMC provisioning complete. The board should now boot from
eMMC: TF-A FSBL → FIP → OP-TEE → U-Boot → extlinux loads
kernel + initramfs from the boot-a partition.
================================================================
EOF
