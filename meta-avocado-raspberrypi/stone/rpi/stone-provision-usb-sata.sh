#!/usr/bin/env bash

# RPi SATA SSD provisioning via rpiboot USB mass storage.
#
# This script provisions a SATA SSD on a CM4-based board (e.g., FR202) by:
# 1. Optionally configuring the EEPROM BOOT_ORDER for the target storage
# 2. Building a raw disk image from the firmware archive
# 3. Patching the U-Boot environment for the SATA target device
# 4. Using rpiboot to expose the SATA SSD as USB mass storage
# 5. Writing the patched image to the SATA SSD
#
# Environment variable overrides:
#   AVOCADO_SKIP_EEPROM_CONFIG=1  - Skip EEPROM BOOT_ORDER configuration
#   AVOCADO_BOOT_ORDER=0x...      - Custom BOOT_ORDER value (default: 0xf614)

set -euo pipefail

# Environment variables provided by avocado:
# AVOCADO_STONE_MANIFEST - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR - stone data directory
# AVOCADO_DEVICE_CERT - device certificate content (base64 encoded pem)
# AVOCADO_DEVICE_KEY - device private key content (base64 encoded pem)
# AVOCADO_DEVICE_ID - device ID

echo "=== RPi SATA SSD Provisioning via rpiboot ==="

# --- Step 0: Configure EEPROM BOOT_ORDER ---
# BOOT_ORDER digits (right to left = first to last):
#   1=SD, 2=network, 4=USB, 5=BCM-USB, 6=NVMe/SATA(PCIe)
# Default for SATA: 0xf614 = PCIe(SATA) -> SD -> USB -> retry
if [[ "${AVOCADO_SKIP_EEPROM_CONFIG:-0}" != "1" ]]; then
    BOOT_ORDER="${AVOCADO_BOOT_ORDER:-0xf614}"
    echo "Configuring EEPROM BOOT_ORDER=${BOOT_ORDER}..."

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

    # Determine recovery directory (CM4 uses 'recovery', Pi5 uses 'recovery5')
    recovery_dir="${sysroot_prefix}/usr/share/rpiboot/recovery"
    if [[ ! -d "$recovery_dir" ]]; then
        echo "Error: recovery directory not found at: $recovery_dir"
        exit 1
    fi

    # Create a temporary recovery directory with modified boot.conf
    # Use -L to dereference symlinks (pieeprom.original.bin is a symlink)
    eeprom_workdir="${AVOCADO_STONE_BUILD_DIR}/eeprom-config"
    rm -rf "$eeprom_workdir"
    cp -rL "$recovery_dir" "$eeprom_workdir"

    # Modify boot.conf with desired BOOT_ORDER
    if [[ -f "$eeprom_workdir/boot.conf" ]]; then
        sed -i "s/^BOOT_ORDER=.*/BOOT_ORDER=${BOOT_ORDER}/" "$eeprom_workdir/boot.conf"
    else
        echo "BOOT_ORDER=${BOOT_ORDER}" > "$eeprom_workdir/boot.conf"
    fi

    echo "Modified boot.conf:"
    grep "BOOT_ORDER" "$eeprom_workdir/boot.conf"

    # Regenerate pieeprom.bin with modified boot.conf using the tools script.
    # The tools script adds its own dir to PATH (for rpi-eeprom-config)
    # and expects pieeprom.original.bin + boot.conf in the working directory.
    tools_dir="${sysroot_prefix}/usr/share/rpiboot/tools"
    if [[ -f "$tools_dir/update-pieeprom.sh" ]]; then
        echo "Regenerating pieeprom.bin..."
        (cd "$eeprom_workdir" && "$tools_dir/update-pieeprom.sh")
    else
        # Fallback: use rpi-eeprom-config directly if available in the recovery dir
        if [[ -x "$eeprom_workdir/rpi-eeprom-config" ]]; then
            echo "Regenerating pieeprom.bin via rpi-eeprom-config..."
            "$eeprom_workdir/rpi-eeprom-config" \
                --config "$eeprom_workdir/boot.conf" \
                --out "$eeprom_workdir/pieeprom.bin" \
                "$eeprom_workdir/pieeprom.original.bin"
        else
            echo "Warning: no tool found to regenerate pieeprom.bin, using existing"
        fi
    fi

    echo "Waiting for rpi boot device to flash EEPROM..."
    VID=0a5c
    PIDS=("2711" "2712")
    TIMEOUT=20
    start_time=$(date +%s)

    while :; do
      now=$(date +%s)
      if (( now - start_time >= TIMEOUT )); then
        echo "Timed out waiting for rpi boot device"
        exit 1
      fi
      for d in /sys/bus/usb/devices/*; do
        [[ -f "$d/idVendor" && -f "$d/idProduct" ]] || continue
        device_vid=$(<"$d/idVendor")
        device_pid=$(<"$d/idProduct")
        if [[ "$device_vid" == "$VID" ]]; then
          for pid in "${PIDS[@]}"; do
            if [[ "$device_pid" == "$pid" ]]; then
              echo "rpi boot device detected (${device_vid}:${device_pid})"
              break 3
            fi
          done
        fi
      done
      echo -n "."
      sleep 0.5
    done

    echo "Flashing EEPROM with BOOT_ORDER=${BOOT_ORDER}..."
    if ! "$rpiboot_path" -d "$eeprom_workdir"; then
        echo "Error: rpiboot EEPROM flash failed"
        exit 1
    fi

    rm -rf "$eeprom_workdir"

    echo "EEPROM configured. Waiting for device to reboot..."
    echo "Please power cycle the device to apply the new EEPROM config,"
    echo "then put it back into USB boot mode."
    echo ""
    read -p "Press Enter when the device is back in USB boot mode..." 2>&1
else
    echo "Skipping EEPROM configuration (AVOCADO_SKIP_EEPROM_CONFIG=1)"
fi

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

# --- Step 2: Patch U-Boot env for SATA target ---
echo "Patching U-Boot environment for SATA SSD..."

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

# FR202 SATA SSD is connected via PCIe -> USB 3.0 XHCI -> USB mass storage.
# In U-Boot, the drive is accessed as a "usb" device.
# In Linux, it appears as /dev/sdaX.
fw_setenv -c "$fw_env_config" devtype usb
fw_setenv -c "$fw_env_config" devnum 0
fw_setenv -c "$fw_env_config" rootdev /dev/sda3
echo "U-Boot env patched for SATA target"

echo "Writing patched env back to image..."
mcopy -o -i "${archive_image}@@${env_offset_bytes}" "${env_workdir}/uboot.env" ::/uboot.env
mcopy -o -i "${archive_image}@@${env_offset_bytes}" "${env_workdir}/uboot.env.redund" ::/uboot.env.redund

rm -rf "$env_workdir" "$fw_env_config"

# --- Step 2b: Patch cmdline.txt in the boot partition ---
# The kernel cmdline root= is baked into cmdline.txt at build time as /dev/mmcblk0p3.
# For USB/SATA targets, the device is /dev/sdaX, so we must patch it.
echo "Patching cmdline.txt for SATA root device..."

boot_offset=$(jq -r '.storage_devices.rootdisk.partitions[] | select(.name == "boot-a") | .offset' "$AVOCADO_STONE_MANIFEST")
boot_offset_unit=$(jq -r '.storage_devices.rootdisk.partitions[] | select(.name == "boot-a") | .offset_unit' "$AVOCADO_STONE_MANIFEST")

case "$boot_offset_unit" in
    "mebibytes") boot_offset_bytes=$((boot_offset * 1024 * 1024)) ;;
    "kibibytes") boot_offset_bytes=$((boot_offset * 1024)) ;;
    "bytes") boot_offset_bytes=$boot_offset ;;
    *) echo "Error: Unknown boot offset unit: $boot_offset_unit"; exit 1 ;;
esac

cmdline_workdir="${AVOCADO_STONE_BUILD_DIR}/cmdline-work"
mkdir -p "$cmdline_workdir"

mcopy -i "${archive_image}@@${boot_offset_bytes}" ::/cmdline.txt "${cmdline_workdir}/cmdline.txt"
echo "Original cmdline.txt:"
cat "${cmdline_workdir}/cmdline.txt"

# Replace root device: mmcblk0p3 -> sda3, also handle mmcblk0p4 -> sda4 for var
sed -i 's|/dev/mmcblk[0-9]*p3|/dev/sda3|g' "${cmdline_workdir}/cmdline.txt"
sed -i 's|/dev/mmcblk[0-9]*p4|/dev/sda4|g' "${cmdline_workdir}/cmdline.txt"

echo "Patched cmdline.txt:"
cat "${cmdline_workdir}/cmdline.txt"

mcopy -o -i "${archive_image}@@${boot_offset_bytes}" "${cmdline_workdir}/cmdline.txt" ::/cmdline.txt
rm -rf "$cmdline_workdir"

# --- Step 2c: Replace U-Boot binary with USB env variant ---
# The default u-boot.bin is compiled with CONFIG_ENV_FAT_INTERFACE="mmc".
# For USB-attached storage, we need the "usb" variant so U-Boot reads
# its environment from usb 0:2 instead of mmc 0:2.
# The variant is deployed as u-boot-usb.bin by the Yocto build.
uboot_usb_variant=$(find "$AVOCADO_STONE_DATA_DIR" -name "u-boot-usb.bin" 2>/dev/null | head -1)
if [[ -n "$uboot_usb_variant" && -f "$uboot_usb_variant" ]]; then
    echo "Replacing U-Boot binary with USB env variant..."
    # On RPi4/CM4, u-boot.bin is deployed as kernel8.img on the boot FAT partition
    mcopy -o -i "${archive_image}@@${boot_offset_bytes}" "$uboot_usb_variant" ::/kernel8.img
    echo "U-Boot binary replaced with USB variant"
else
    echo "WARNING: u-boot-usb.bin not found in stone data directory."
    echo "U-Boot will use the default mmc env config, which may not work for USB storage."
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
    # Fallback to 32-bit gadget for CM4
    mass_storage_gadget_path="${sysroot_prefix}/usr/share/rpiboot/mass-storage-gadget"
    if [[ ! -d "$mass_storage_gadget_path" ]]; then
        echo "Error: mass-storage-gadget directory not found"
        exit 1
    fi
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

# --- Step 4: Write the patched image ---
echo "Writing patched system image to SATA SSD..."

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
echo "Image size: ${image_size_mib} MiB"
echo "Writing ${image_size_mib} MiB to ${rpi_block_device}..."

if ! dd if="${archive_image}" of="${rpi_block_device}" bs=4M status=progress conv=fsync; then
    echo "Error: Failed to write system image to SATA SSD"
    exit 1
fi
echo "Write complete. Syncing..."
sync

echo ""
echo "=== SATA SSD provisioning complete ==="
echo "Please disconnect the USB cable and power cycle the device."
if [[ "${AVOCADO_SKIP_EEPROM_CONFIG:-0}" != "1" ]]; then
    echo "EEPROM BOOT_ORDER has been configured to boot from PCIe/SATA."
else
    echo "Remember to configure the EEPROM BOOT_ORDER to include PCIe/SATA (digit 6)."
    echo "Example: BOOT_ORDER=0xf614  (SATA -> SD -> USB -> retry)"
fi

exit 0
