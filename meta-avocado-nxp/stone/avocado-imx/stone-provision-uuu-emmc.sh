#!/usr/bin/env bash

set -euo pipefail

# Environment variables provided by stone:
# AVOCADO_STONE_MANIFEST - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR - stone data directory
# AVOCADO_DEVICE_CERT - device certificate content (base64 encoded pem)
# AVOCADO_DEVICE_KEY - device private key content (base64 encoded pem)
# AVOCADO_DEVICE_ID - device ID

echo "=== iMX eMMC Provisioning via uuu ==="
echo "Manifest: $AVOCADO_STONE_MANIFEST"
echo "Data dir: $AVOCADO_STONE_DATA_DIR"
echo "Build dir: $AVOCADO_STONE_BUILD_DIR"

# --- Step 1: Build the raw disk image from the fwup archive ---
archive_name=$(jq -r .storage_devices.rootdisk.out "$AVOCADO_STONE_MANIFEST")
archive_file="${AVOCADO_STONE_BUILD_DIR}/${archive_name}"
archive_image="${archive_file%%.*}.img"

if [ ! -f "$archive_image" ]; then
    echo "Building disk image from archive..."
    fwup \
      -a \
      -i "${archive_file}" \
      -d "${archive_image}" \
      -t complete
    echo "Disk image created: $archive_image"
else
    echo "Using existing disk image: $archive_image"
fi

# --- Step 2: Read per-machine eMMC parameters from manifest ---
# emmc_uboot_dev: U-Boot mmc device number (e.g. 2 on iMX8MP EVK, 0 on iMX93 FRDM)
# emmc_mmcblk:    Linux mmcblkN block device number for eMMC
profile_config_path='.provision.profiles."uuu-emmc".config'
emmc_uboot_dev=$(jq -r "${profile_config_path}.emmc_uboot_dev // empty" "$AVOCADO_STONE_MANIFEST")
emmc_mmcblk=$(jq -r "${profile_config_path}.emmc_mmcblk // empty" "$AVOCADO_STONE_MANIFEST")
if [ -z "$emmc_uboot_dev" ] || [ -z "$emmc_mmcblk" ]; then
    echo "ERROR: provision.profiles.uuu-emmc.config must define emmc_uboot_dev and emmc_mmcblk"
    exit 1
fi

# --- Step 3: Patch U-Boot env to point root/devnum at eMMC ---
echo "Patching U-Boot environment for eMMC boot (devnum=${emmc_uboot_dev}, mmcblk=${emmc_mmcblk})..."

fw_env_img_config="${AVOCADO_STONE_BUILD_DIR}/fw_env_img.config"
cat > "$fw_env_img_config" << EOF
${archive_image}	0x400000	0x20000	0x200	256
${archive_image}	0x440000	0x20000	0x200	256
EOF

fw_setenv -c "$fw_env_img_config" devnum "$emmc_uboot_dev"
fw_setenv -c "$fw_env_img_config" mmcblk "$emmc_mmcblk"
echo "U-Boot env patched: devnum=${emmc_uboot_dev}, mmcblk=${emmc_mmcblk}"

# --- Step 4: Locate imx-boot image for the SDPS handoff ---
# iMX8M: prefer the emmc_fastboot variant (mkimage_imx8 -dev emmc_fastboot),
#        which configures the legacy boot container for USB→fastboot handoff.
# iMX9:  AHAB-based flash_singleboot is reused directly; U-Boot enters fastboot
#        via CONFIG_FASTBOOT_UUU_SUPPORT, no separate variant exists.
imx_boot_name=$(jq -r '.storage_devices.rootdisk.images.imx_boot_emmc_fastboot // empty' "$AVOCADO_STONE_MANIFEST")
if [ -z "$imx_boot_name" ]; then
    imx_boot_name=$(jq -r '.storage_devices.rootdisk.images.imx_boot // empty' "$AVOCADO_STONE_MANIFEST")
fi
if [ -z "$imx_boot_name" ]; then
    echo "ERROR: no imx_boot image specified in manifest"
    exit 1
fi

imx_boot_path="${AVOCADO_STONE_DATA_DIR}/${imx_boot_name}"
if [ ! -f "$imx_boot_path" ]; then
    echo "ERROR: imx-boot not found at $imx_boot_path"
    exit 1
fi
echo "Using imx-boot: $imx_boot_path"

# --- Step 5: Wait for device in serial download mode ---
# NXP i.MX devices in serial download mode use USB vendor IDs:
#   1fc9 (NXP) or 15a2 (Freescale legacy)
check_sdp() {
    lsusb -d 1fc9: >/dev/null 2>&1 || lsusb -d 15a2: >/dev/null 2>&1
}

if check_sdp; then
    echo "Device detected in serial download mode"
else
    echo "Please put device into serial download mode..."
    echo "(Hold BOOT button, press and release RESET, then release BOOT)"
    for i in $(seq 1 60); do
        if check_sdp; then
            echo "Device detected in serial download mode"
            break
        fi
        sleep 1
    done
    if ! check_sdp; then
        echo "ERROR: Device not detected in serial download mode (waited 60s)"
        exit 1
    fi
fi

# --- Step 6: Generate custom uuu script and flash ---
# uuu resolves file paths relative to the .uuu script location,
# so we symlink/copy files into the build dir and use bare filenames.
uuu_dir="${AVOCADO_STONE_BUILD_DIR}/uuu"
mkdir -p "$uuu_dir"

ln -sf "$imx_boot_path" "$uuu_dir/imx-boot"
ln -sf "$archive_image" "$uuu_dir/rootdisk.img"

# Standard imx-boot (non-fastboot variant) for writing to the eMMC boot
# partition. On iMX8M this differs from the SDPS payload; on iMX9 they are
# the same image. Always link it so the .uuu script can reference it.
imx_boot_sd_name=$(jq -r '.storage_devices.rootdisk.images.imx_boot // empty' "$AVOCADO_STONE_MANIFEST")
if [ -n "$imx_boot_sd_name" ]; then
    ln -sf "${AVOCADO_STONE_DATA_DIR}/${imx_boot_sd_name}" "$uuu_dir/imx-boot-sd"
else
    ln -sf "$imx_boot_path" "$uuu_dir/imx-boot-sd"
fi

uuu_script="${uuu_dir}/flash_emmc.uuu"
cat > "$uuu_script" << EOF
uuu_version 1.2.39

# Boot U-Boot via SDPS
SDPS: boot -f imx-boot

# U-Boot enters fastboot mode (iMX8M: -dev emmc_fastboot container;
# iMX9: CONFIG_FASTBOOT_UUU_SUPPORT in U-Boot). Select eMMC as the target.
FB: ucmd setenv fastboot_dev mmc
FB: ucmd setenv mmcdev ${emmc_uboot_dev}
FB: ucmd mmc dev ${emmc_uboot_dev}

# Write the raw disk image to eMMC user data area
FB[-t 600000]: flash -raw2sparse all rootdisk.img

# Write imx-boot to the eMMC hardware boot partition.
# This replaces any factory bootloader and ensures our U-Boot is used on next boot.
FB: flash bootloader imx-boot-sd

# Configure eMMC to boot from boot partition 1 (ack=0, boot_partition=1, access=0)
FB: ucmd if env exists emmc_ack; then ; else setenv emmc_ack 0; fi;
FB: ucmd mmc partconf ${emmc_uboot_dev} \${emmc_ack} 1 0

FB: done
EOF

echo "Flashing to eMMC via uuu..."
echo "  Bootloader: $imx_boot_path"
echo "  Disk image: $archive_image"
echo "  eMMC dev: $emmc_uboot_dev"
echo "  Script: $uuu_script"
echo ""
cat "$uuu_script"
echo ""

uuu -v "$uuu_script"

echo "=== eMMC provisioning complete ==="
