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

Before continuing, confirm:
  1. The bootloader has been programmed to SPI NOR (Phase 1 'serial' profile).
  2. DIP S5 is in SPI boot mode (MD0=OFF, MD1=ON).
  3. The USB-OTG cable is connected from the SoM to this host.
  4. The board is powered on; U-Boot has entered fastboot
     (typical when no OS image is present in eMMC or SD).

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

# Write the partition table first, then each populated partition.
# `fastboot flash gpt` accepts a full disk image and only consumes the GPT
# header/backup regions; subsequent per-partition flashes target the named
# slots without re-touching the GPT.
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
eMMC: U-Boot's distro_bootcmd will probe mmc0, find
/extlinux/extlinux.conf on the boot-a partition, and load the
Avocado kernel.
================================================================
EOF
