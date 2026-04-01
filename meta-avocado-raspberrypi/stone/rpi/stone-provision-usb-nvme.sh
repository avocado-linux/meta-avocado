#!/usr/bin/env bash

# RPi NVMe provisioning via rpiboot USB mass storage.
#
# This script provisions an NVMe-equipped RPi (Pi5/CM5) by:
# 1. Building a raw disk image from the firmware archive
# 2. Patching the U-Boot environment for the NVMe target device
# 3. Using rpiboot to expose the NVMe as USB mass storage
# 4. Writing the patched image to the NVMe device
# 5. Setting device-specific env values (device ID, certs)

set -euo pipefail

# Environment variables provided by avocado:
# AVOCADO_STONE_MANIFEST - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR - stone data directory
# AVOCADO_DEVICE_CERT - device certificate content (base64 encoded pem)
# AVOCADO_DEVICE_KEY - device private key content (base64 encoded pem)
# AVOCADO_DEVICE_ID - device ID

echo "=== RPi NVMe Provisioning via rpiboot ==="

# --- Step 1: Build the raw disk image ---
archive_name=$(jq -r .storage_devices.rootdisk.out "$AVOCADO_STONE_MANIFEST")
archive_file="${AVOCADO_STONE_BUILD_DIR}/${archive_name}"
archive_image="${archive_file%%.*}.img"

if [[ -z "$archive_name" || "$archive_name" == "null" ]]; then
    echo "Error: Could not extract archive name from manifest"
    exit 1
fi

if [[ ! -f "$archive_file" ]]; then
    echo "Error: Archive file not found: $archive_file"
    exit 1
fi

# Always rebuild from the archive — different provisioning profiles patch
# the image differently (U-Boot binary, env vars, cmdline), so reusing a
# cached image from another profile produces a broken result.
echo "Building disk image from archive..."
rm -f "${archive_image}"
fwup \
  -a \
  -i "${archive_file}" \
  -d "${archive_image}" \
  -t complete
echo "Disk image created: $archive_image"

# --- Step 2: Patch U-Boot env for NVMe target ---
echo "Patching U-Boot environment for NVMe..."

env_offset=$(jq -r '.storage_devices.rootdisk.partitions[] | select(.name == "uboot-env") | .offset' "$AVOCADO_STONE_MANIFEST")
env_offset_unit=$(jq -r '.storage_devices.rootdisk.partitions[] | select(.name == "uboot-env") | .offset_unit' "$AVOCADO_STONE_MANIFEST")
env_size=$(jq -r '.storage_devices.rootdisk.partitions[] | select(.name == "uboot-env") | .size' "$AVOCADO_STONE_MANIFEST")
env_size_unit=$(jq -r '.storage_devices.rootdisk.partitions[] | select(.name == "uboot-env") | .size_unit' "$AVOCADO_STONE_MANIFEST")

if [[ -z "$env_offset" || "$env_offset" == "null" ]]; then
    echo "Error: Could not extract uboot-env offset from manifest"
    exit 1
fi

case "$env_offset_unit" in
    "mebibytes") env_offset_bytes=$((env_offset * 1024 * 1024)) ;;
    "kibibytes") env_offset_bytes=$((env_offset * 1024)) ;;
    "bytes") env_offset_bytes=$env_offset ;;
    *) echo "Error: Unknown offset unit: $env_offset_unit"; exit 1 ;;
esac

case "$env_size_unit" in
    "mebibytes") env_size_bytes=$((env_size * 1024 * 1024)) ;;
    "kibibytes") env_size_bytes=$((env_size * 1024)) ;;
    "bytes") env_size_bytes=$env_size ;;
    *) echo "Error: Unknown size unit: $env_size_unit"; exit 1 ;;
esac

env_workdir="${AVOCADO_STONE_BUILD_DIR}/uboot-env-work"
mkdir -p "$env_workdir"

echo "Extracting env files from image at offset $env_offset_bytes..."
mcopy -i "${archive_image}@@${env_offset_bytes}" ::/uboot.env "${env_workdir}/uboot.env"
mcopy -i "${archive_image}@@${env_offset_bytes}" ::/uboot.env.redund "${env_workdir}/uboot.env.redund"

fw_env_config="${AVOCADO_STONE_BUILD_DIR}/fw_env_img.config"
cat > "$fw_env_config" << EOF
${env_workdir}/uboot.env	0x0	0x20000
${env_workdir}/uboot.env.redund	0x0	0x20000
EOF

echo "Setting device-specific environment values..."
fw_setenv -c "$fw_env_config" avocado_boot_slot a
fw_setenv -c "$fw_env_config" avocado_device_id "${AVOCADO_DEVICE_ID:-}"
fw_setenv -c "$fw_env_config" avocado_device_cert "${AVOCADO_DEVICE_CERT:-}"
fw_setenv -c "$fw_env_config" avocado_device_key "${AVOCADO_DEVICE_KEY:-}"
fw_setenv -c "$fw_env_config" a.avocado_platform "$(jq -r .runtime.platform "$AVOCADO_STONE_MANIFEST")"
fw_setenv -c "$fw_env_config" a.avocado_architecture "$(jq -r .runtime.architecture "$AVOCADO_STONE_MANIFEST")"

# NVMe-specific: U-Boot loads kernel from NVMe, rootfs on NVMe
fw_setenv -c "$fw_env_config" devtype nvme
fw_setenv -c "$fw_env_config" devnum 0
fw_setenv -c "$fw_env_config" rootdev /dev/nvme0n1p3
echo "U-Boot env patched for NVMe target"

echo "Writing patched env back to image..."
mcopy -o -i "${archive_image}@@${env_offset_bytes}" "${env_workdir}/uboot.env" ::/uboot.env
mcopy -o -i "${archive_image}@@${env_offset_bytes}" "${env_workdir}/uboot.env.redund" ::/uboot.env.redund

rm -rf "$env_workdir" "$fw_env_config"

# --- Step 2b: Replace U-Boot binary with NVMe env variant ---
# The default u-boot.bin is compiled with CONFIG_ENV_FAT_INTERFACE="mmc".
# For NVMe boot, we need the "nvme" variant so U-Boot reads its environment
# from nvme 0:2 instead of mmc 0:2.
# The variant is deployed as u-boot-nvme.bin by the Yocto build.
boot_offset=$(jq -r '.storage_devices.rootdisk.partitions[] | select(.name == "boot-a") | .offset' "$AVOCADO_STONE_MANIFEST")
boot_offset_unit=$(jq -r '.storage_devices.rootdisk.partitions[] | select(.name == "boot-a") | .offset_unit' "$AVOCADO_STONE_MANIFEST")

case "$boot_offset_unit" in
    "mebibytes") boot_offset_bytes=$((boot_offset * 1024 * 1024)) ;;
    "kibibytes") boot_offset_bytes=$((boot_offset * 1024)) ;;
    "bytes") boot_offset_bytes=$boot_offset ;;
    *) echo "Error: Unknown boot offset unit: $boot_offset_unit"; exit 1 ;;
esac

uboot_nvme_variant=$(find "$AVOCADO_STONE_DATA_DIR" -name "u-boot-nvme.bin" 2>/dev/null | head -1)
if [[ -n "$uboot_nvme_variant" && -f "$uboot_nvme_variant" ]]; then
    echo "Replacing U-Boot binary with NVMe env variant..."
    # On Pi5/CM5, u-boot.bin is deployed as kernel_2712.img on the boot FAT partition
    mcopy -o -i "${archive_image}@@${boot_offset_bytes}" "$uboot_nvme_variant" ::/kernel_2712.img
    echo "U-Boot binary replaced with NVMe variant"
else
    echo "WARNING: u-boot-nvme.bin not found in stone data directory."
    echo "U-Boot will use the default mmc env config, which will not work for NVMe storage."
    echo "Searched: $AVOCADO_STONE_DATA_DIR"
fi

# --- Step 3: Detect rpiboot device and enter mass storage mode ---
VID=0a5c
PIDS=("2711" "2712")
TIMEOUT=20

start_time=$(date +%s)
last_boot_dot_time=0
echo "Waiting for rpi boot device to be detected..."

while :; do
  now=$(date +%s)
  if (( now - last_boot_dot_time >= 2 )); then
    echo -n "."
    last_boot_dot_time=$now
  fi
  for d in /sys/bus/usb/devices/*; do
    [[ -f "$d/idVendor" && -f "$d/idProduct" ]] || continue
    device_vid=$(<"$d/idVendor")
    device_pid=$(<"$d/idProduct")
    if [[ "$device_vid" == "$VID" ]]; then
      for pid in "${PIDS[@]}"; do
        if [[ "$device_pid" == "$pid" ]]; then
          echo ""
          echo "rpi boot device detected at $(basename "$d") (${device_vid}:${device_pid})"
          found=true
          break 3
        fi
      done
    fi
  done
  now=$(date +%s)
  if (( now - start_time >= TIMEOUT )); then
    echo ""
    echo "Timed out after $TIMEOUT seconds waiting for rpi boot device"
    exit 1
  fi
  sleep 0.5
done

existing_devices=()
for block_dev in /sys/block/sd*; do
    [[ -d "$block_dev" ]] || continue
    existing_devices+=("$(basename "$block_dev")")
done

rpiboot_path=$(which rpiboot)
if [[ -z "$rpiboot_path" ]]; then
    echo "Error: rpiboot not found in PATH"
    exit 1
fi

if [[ "$rpiboot_path" =~ ^(.*)/usr/ ]]; then
    sysroot_prefix="${BASH_REMATCH[1]}"
else
    echo "Error: Could not determine sysroot prefix from rpiboot path: $rpiboot_path"
    exit 1
fi

mass_storage_gadget_path="${sysroot_prefix}/usr/share/rpiboot/mass-storage-gadget64"
if [[ ! -d "$mass_storage_gadget_path" ]]; then
    echo "Error: mass-storage-gadget64 directory not found at: $mass_storage_gadget_path"
    exit 1
fi

echo "Executing rpiboot to enable mass storage mode..."
if ! "$rpiboot_path" -d "$mass_storage_gadget_path"; then
    echo "Error: rpiboot failed to execute"
    exit 1
fi

STORAGE_TIMEOUT=60
storage_start_time=$(date +%s)
rpi_block_device=""
echo "Waiting for rpi to appear as mass storage device..."

while [[ -z "$rpi_block_device" ]]; do
    now=$(date +%s)
    if (( now - storage_start_time >= STORAGE_TIMEOUT )); then
        echo ""
        echo "Timed out after $STORAGE_TIMEOUT seconds waiting for RPi mass storage device"
        exit 1
    fi

    available_devices=$(fwup -D 2>/dev/null | grep "^/dev/sd" || true)
    if [[ -n "$available_devices" ]]; then
        for device_entry in $available_devices; do
            device_path="${device_entry%,*}"
            rpi_device_size_bytes="${device_entry#*,}"
            device_name=$(basename "$device_path")
            device_is_new=true
            for existing_dev in "${existing_devices[@]}"; do
                if [[ "$device_name" == "$existing_dev" ]]; then
                    device_is_new=false
                    break
                fi
            done
            if [[ "$device_is_new" == "true" ]]; then
                rpi_block_device="$device_path"
                echo ""
                echo "Found new mass storage device: $rpi_block_device"
                break
            fi
        done
    fi
    echo -n "."
    sleep 1
done

sleep 2
if [[ -b "$rpi_block_device" ]]; then
    timeout 5 dd if="$rpi_block_device" of=/dev/null bs=512 count=1 2>/dev/null || true
fi

# Query device size via sysfs (always available, no blockdev/bc needed)
device_name=$(basename "$rpi_block_device")
size_sectors=$(cat /sys/block/${device_name}/size 2>/dev/null || echo "0")
rpi_device_size_bytes=$((size_sectors * 512))
device_size_gib=$((rpi_device_size_bytes / 1073741824))
echo ""
echo "WARNING: This will completely overwrite $rpi_block_device (${device_size_gib} GiB)!"
read -p "Are you sure you want to continue? (y/N): " -r 2>&1
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Operation cancelled by user"
    exit 1
fi

# --- Step 4: Write the image ---
echo "Writing patched system image to NVMe..."

if mount | grep -q "${rpi_block_device}"; then
    umount "${rpi_block_device}"* 2>/dev/null || true
fi

sleep 2

if ! dd if="${rpi_block_device}" of=/dev/null bs=512 count=1 2>/dev/null; then
    echo "Error: Device ${rpi_block_device} is not accessible"
    exit 1
fi

image_size=$(stat -c%s "${archive_image}" 2>/dev/null || stat -f%z "${archive_image}" 2>/dev/null || echo "unknown")
image_size_mib=$((${image_size:-0} / 1024 / 1024))
echo "Writing ${image_size_mib} MiB to ${rpi_block_device}..."

if ! dd if="${archive_image}" of="${rpi_block_device}" bs=4M status=progress conv=fsync; then
    echo "Error: Failed to write system image to NVMe"
    exit 1
fi
echo "Write complete. Syncing..."
sync

echo ""
echo "=== NVMe provisioning complete ==="
echo "Please disconnect the USB cable and power cycle the device."
echo "Ensure the EEPROM boot order includes NVMe (use rpi-eeprom-config to verify)."
echo "Example: BOOT_ORDER=0xf461  (NVMe -> SD -> USB -> network)"

exit 0
