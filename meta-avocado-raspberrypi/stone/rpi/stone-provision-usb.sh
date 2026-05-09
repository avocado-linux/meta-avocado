#!/usr/bin/env bash

# Exit immediately if any command fails
set -e
# Exit on undefined variables
set -u
# Propagate errors in pipelines
set -o pipefail

# Environment variables provided by avocado:
# AVOCADO_STONE_MANIFEST - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR - stone data directory
# AVOCADO_DEVICE_CERT - device certificate content (base64 encoded pem)
# AVOCADO_DEVICE_KEY - device private key content (base64 encoded pem)
# AVOCADO_DEVICE_ID - device ID

archive_name=$(cat "$AVOCADO_STONE_MANIFEST" | jq -r .storage_devices.rootdisk.out)
if [[ -z "$archive_name" || "$archive_name" == "null" ]]; then
    echo "Error: Could not extract archive name from manifest"
    exit 1
fi

archive_file="${AVOCADO_STONE_BUILD_DIR}/${archive_name}"
if [[ ! -f "$archive_file" ]]; then
    echo "Error: Archive file not found: $archive_file"
    exit 1
fi

VID=0a5c
# Supported boot device PIDs: BCM2711 (Pi4/CM4) and BCM2712 (Pi5)
PIDS=("2711" "2712")
TIMEOUT=20

# --- Step 0: Configure EEPROM BOOT_ORDER (optional) ---
# BOOT_ORDER nibbles read right-to-left (first attempt -> last):
#   1=SD, 2=network, 4=USB, 5=BCM-USB, 6=NVMe/SATA(PCIe), f=restart
# Default 0xf41 = SD -> USB -> restart. Useful when re-flashing SD on a
# board whose EEPROM was previously set NVMe/PCIe-first.
#   AVOCADO_SKIP_EEPROM_CONFIG=1  - skip this step
#   AVOCADO_BOOT_ORDER=0x...      - override BOOT_ORDER value
if [[ "${AVOCADO_SKIP_EEPROM_CONFIG:-0}" != "1" ]]; then
    BOOT_ORDER="${AVOCADO_BOOT_ORDER:-0xf41}"
    echo "=== Step 0: Configure EEPROM BOOT_ORDER=${BOOT_ORDER} ==="

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

    echo "Waiting for rpi boot device for EEPROM flash..."
    eeprom_start=$(date +%s)
    detected_pid=""
    while :; do
        now=$(date +%s)
        if (( now - eeprom_start >= TIMEOUT )); then
            echo ""
            echo "Timed out after $TIMEOUT seconds waiting for rpi boot device"
            exit 1
        fi
        for d in /sys/bus/usb/devices/*; do
            [[ -f "$d/idVendor" && -f "$d/idProduct" ]] || continue
            device_vid=$(<"$d/idVendor")
            device_pid=$(<"$d/idProduct")
            if [[ "$device_vid" == "$VID" ]]; then
                for pid in "${PIDS[@]}"; do
                    if [[ "$device_pid" == "$pid" ]]; then
                        detected_pid="$pid"
                        break 3
                    fi
                done
            fi
        done
        echo -n "."
        sleep 0.5
    done
    echo ""
    echo "rpi boot device detected (${VID}:${detected_pid})"

    # PID 2712 (Pi5) uses recovery5; PID 2711 (Pi4/CM4) uses recovery.
    if [[ "$detected_pid" == "2712" ]]; then
        recovery_subdir="recovery5"
    else
        recovery_subdir="recovery"
    fi
    recovery_dir="${sysroot_prefix}/usr/share/rpiboot/${recovery_subdir}"
    if [[ ! -d "$recovery_dir" ]]; then
        echo "Error: recovery directory not found at: $recovery_dir"
        exit 1
    fi

    # Build a workdir copy with the desired BOOT_ORDER baked into boot.conf.
    # -L dereferences pieeprom.original.bin, which ships as a symlink.
    eeprom_workdir="${AVOCADO_STONE_BUILD_DIR}/eeprom-config"
    rm -rf "$eeprom_workdir"
    cp -rL "$recovery_dir" "$eeprom_workdir"

    if [[ -f "$eeprom_workdir/boot.conf" ]]; then
        sed -i "s/^BOOT_ORDER=.*/BOOT_ORDER=${BOOT_ORDER}/" "$eeprom_workdir/boot.conf"
    else
        echo "BOOT_ORDER=${BOOT_ORDER}" > "$eeprom_workdir/boot.conf"
    fi
    grep "BOOT_ORDER" "$eeprom_workdir/boot.conf"

    tools_dir="${sysroot_prefix}/usr/share/rpiboot/tools"
    if [[ ! -f "$tools_dir/update-pieeprom.sh" ]]; then
        echo "Error: update-pieeprom.sh not found at $tools_dir/update-pieeprom.sh"
        exit 1
    fi
    echo "Regenerating pieeprom.bin..."
    (cd "$eeprom_workdir" && "$tools_dir/update-pieeprom.sh")

    echo "Flashing EEPROM..."
    if ! "$rpiboot_path" -d "$eeprom_workdir"; then
        echo "Error: rpiboot EEPROM flash failed"
        exit 1
    fi
    rm -rf "$eeprom_workdir"

    echo ""
    echo "EEPROM flashed with BOOT_ORDER=${BOOT_ORDER}."
    echo "Power-cycle the device and put it back into USB boot mode,"
    read -p "then press Enter to continue. " 2>&1
else
    echo "Skipping EEPROM configuration (AVOCADO_SKIP_EEPROM_CONFIG=1)"
fi

start_time=$(date +%s)
last_boot_dot_time=0
echo "Waiting for rpi boot device to be detected..."

while :; do
  # Show progress dots every 2 seconds
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
          echo ""  # New line after progress dots
          echo "rpi boot device detected at $(basename "$d") (${device_vid}:${device_pid})"
          found=true
          break 3   # break out of all loops
        fi
      done
    fi
  done

  # Check timeout
  now=$(date +%s)
  if (( now - start_time >= TIMEOUT )); then
    echo ""  # New line after progress dots
    echo "Timed out after $TIMEOUT seconds waiting for rpi boot device"
    exit 1
  fi

  sleep 0.5
done

# Record existing block devices before enabling mass storage mode
echo "Recording existing block devices..."
existing_devices=()
for block_dev in /sys/block/sd*; do
    [[ -d "$block_dev" ]] || continue
    existing_devices+=("$(basename "$block_dev")")
done
if [[ ${#existing_devices[@]} -eq 0 ]]; then
    echo "Existing devices: none"
else
    echo "Existing devices: ${existing_devices[*]}"
fi

# Find rpiboot and determine the sysroot prefix
rpiboot_path=$(which rpiboot)
if [[ -z "$rpiboot_path" ]]; then
    echo "Error: rpiboot not found in PATH"
    exit 1
fi

# Extract the prefix by finding the /usr level in the path
# Example: /path/to/sysroot/usr/bin/rpiboot -> /path/to/sysroot
# Example: /path/to/sysroot/usr/local/bin/rpiboot -> /path/to/sysroot
if [[ "$rpiboot_path" =~ ^(.*)/usr/ ]]; then
    sysroot_prefix="${BASH_REMATCH[1]}"
else
    echo "Error: Could not determine sysroot prefix from rpiboot path: $rpiboot_path"
    exit 1
fi

mass_storage_gadget_path="${sysroot_prefix}/usr/share/rpiboot/mass-storage-gadget64"

# Verify the mass-storage-gadget64 directory exists
if [[ ! -d "$mass_storage_gadget_path" ]]; then
    echo "Error: mass-storage-gadget64 directory not found at: $mass_storage_gadget_path"
    exit 1
fi

echo "Using rpiboot at: $rpiboot_path"
echo "Using mass-storage-gadget64 at: $mass_storage_gadget_path"

# Execute rpiboot to put the rpi into mass storage mode
echo "Executing rpiboot to enable mass storage mode..."
if ! "$rpiboot_path" -d "$mass_storage_gadget_path"; then
    echo "Error: rpiboot failed to execute"
    exit 1
fi

echo "Waiting for rpi to appear as mass storage device..."

# Wait for the RPi mass storage device to appear
# Looking for USB device 0a5c:0104 and corresponding block device
STORAGE_TIMEOUT=60
storage_start_time=$(date +%s)
rpi_block_device=""
last_dot_time=0

while [[ -z "$rpi_block_device" ]]; do
    # Show progress dots every 2 seconds
    now=$(date +%s)
    if (( now - last_dot_time >= 2 )); then
        echo -n "."
        last_dot_time=$now
    fi
    
    # Use fwup -D to detect available devices
    available_devices=$(fwup -D 2>/dev/null | grep "^/dev/sd" || true)
    
    if [[ -n "$available_devices" ]]; then
        echo ""  # New line after progress dots
        
        # Check each device fwup found (format: /dev/sdX,size_in_bytes)
        for device_entry in $available_devices; do
            # Parse device path and size from fwup output
            device_path="${device_entry%,*}"
            device_size_bytes="${device_entry#*,}"
            device_name=$(basename "$device_path")
            
            # Skip devices that existed before mass storage mode
            device_is_new=true
            for existing_dev in "${existing_devices[@]}"; do
                if [[ "$device_name" == "$existing_dev" ]]; then
                    device_is_new=false
                    break
                fi
            done
            
            if [[ "$device_is_new" == "true" ]]; then
                # Use the first new device fwup detects
                rpi_block_device="$device_path"
                rpi_device_size_bytes="$device_size_bytes"
                echo "Found new mass storage device: $rpi_block_device"
                break
            fi
        done
    fi
    
    # Check timeout
    now=$(date +%s)
    if (( now - storage_start_time >= STORAGE_TIMEOUT )); then
        echo ""  # New line after progress dots
        echo "Timed out after $STORAGE_TIMEOUT seconds waiting for RPi mass storage device"
        echo "Diagnostic information:"
        echo "USB devices currently detected:"
        for d in /sys/bus/usb/devices/*; do
            [[ -f "$d/idVendor" && -f "$d/idProduct" ]] || continue
            vid=$(<"$d/idVendor")
            pid=$(<"$d/idProduct")
            echo "  USB device $(basename "$d"): $vid:$pid"
        done
        echo "Block devices currently present:"
        for block_dev in /sys/block/sd*; do
            [[ -d "$block_dev" ]] || continue
            device_name=$(basename "$block_dev")
            if [[ -f "$block_dev/device/vendor" && -f "$block_dev/device/model" ]]; then
                vendor=$(cat "$block_dev/device/vendor" 2>/dev/null | xargs)
                model=$(cat "$block_dev/device/model" 2>/dev/null | xargs)
                echo "  Block device $device_name: vendor='$vendor' model='$model'"
            else
                echo "  Block device $device_name: no vendor/model info"
            fi
        done
        exit 1
    fi
    
    sleep 1
done

# Wait for the block device to be fully accessible
echo "Waiting for block device to be ready for access..."
DEVICE_READY_TIMEOUT=15
device_ready_start_time=$(date +%s)
device_ready=false

while [[ "$device_ready" == "false" ]]; do
    # Check if device exists as a block device
    if [[ -b "$rpi_block_device" ]]; then
        # Try a simple read test first
        if timeout 2 dd if="$rpi_block_device" of=/dev/null bs=512 count=1 2>/dev/null; then
            device_ready=true
            echo ""  # New line after progress dots
            echo "Block device is ready for access"
            break
        else
            # If dd fails, check if it's just a permission issue by testing file existence
            if [[ -r "$rpi_block_device" ]]; then
                echo ""  # New line after progress dots
                echo "Block device exists and is readable, proceeding..."
                device_ready=true
                break
            fi
        fi
    fi
    
    # Check timeout
    now=$(date +%s)
    if (( now - device_ready_start_time >= DEVICE_READY_TIMEOUT )); then
        echo ""  # New line after progress dots
        echo "Device status: block device exists: $([[ -b "$rpi_block_device" ]] && echo "yes" || echo "no")"
        echo "Device status: readable: $([[ -r "$rpi_block_device" ]] && echo "yes" || echo "no")"
        echo "Proceeding anyway - device may be ready despite timeout"
        break
    fi
    
    echo -n "."
    sleep 0.5
done

# Ensure we actually found a device
if [[ -z "$rpi_block_device" ]]; then
    echo "Error: No new RPi mass storage device was detected"
    exit 1
fi

# Calculate device size in GiB
device_size_gib=$((rpi_device_size_bytes / 1024 / 1024 / 1024))
device_size_gib_decimal=$(echo "scale=2; $rpi_device_size_bytes / 1024 / 1024 / 1024" | bc -l 2>/dev/null || echo "$device_size_gib")

echo "rpi successfully ready as mass storage device:"
echo "  Device: $rpi_block_device"
echo "  Size: ${device_size_gib_decimal} GiB (${rpi_device_size_bytes} bytes)"

# Get device vendor/model info if available
block_dev="/sys/block/$(basename "$rpi_block_device")"
if [[ -d "$block_dev" ]]; then
    vendor_file="$block_dev/device/vendor"
    model_file="$block_dev/device/model"
    if [[ -f "$vendor_file" && -f "$model_file" ]]; then
        vendor=$(cat "$vendor_file" 2>/dev/null | xargs)
        model=$(cat "$model_file" 2>/dev/null | xargs)
        echo "  Vendor: $vendor"
        echo "  Model: $model"
    fi
fi

echo ""
echo "WARNING: This will completely overwrite the device $rpi_block_device!"
echo "All existing data on this ${device_size_gib_decimal} GiB device will be lost."
echo ""

read -p "Are you sure you want to continue? (y/N): " -r 2>&1

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Operation cancelled by user"
    exit 1
fi

echo "User confirmed. Proceeding with firmware write..."

# Extract uboot-env partition info from manifest to clear it
echo "Clearing uboot-env partition..."
uboot_offset=$(cat "$AVOCADO_STONE_MANIFEST" | jq -r '.storage_devices.rootdisk.partitions[] | select(.name == "uboot-env") | .offset')
uboot_offset_unit=$(cat "$AVOCADO_STONE_MANIFEST" | jq -r '.storage_devices.rootdisk.partitions[] | select(.name == "uboot-env") | .offset_unit')
uboot_size=$(cat "$AVOCADO_STONE_MANIFEST" | jq -r '.storage_devices.rootdisk.partitions[] | select(.name == "uboot-env") | .size')
uboot_size_unit=$(cat "$AVOCADO_STONE_MANIFEST" | jq -r '.storage_devices.rootdisk.partitions[] | select(.name == "uboot-env") | .size_unit')

# Validate extracted values
if [[ -z "$uboot_offset" || "$uboot_offset" == "null" ]]; then
    echo "Error: Could not extract uboot-env offset from manifest"
    exit 1
fi
if [[ -z "$uboot_size" || "$uboot_size" == "null" ]]; then
    echo "Error: Could not extract uboot-env size from manifest"
    exit 1
fi

# Convert offset to bytes
case "$uboot_offset_unit" in
    "mebibytes") uboot_offset_bytes=$((uboot_offset * 1024 * 1024)) ;;
    "kibibytes") uboot_offset_bytes=$((uboot_offset * 1024)) ;;
    "bytes") uboot_offset_bytes=$uboot_offset ;;
    *) echo "Error: Unknown offset unit: $uboot_offset_unit"; exit 1 ;;
esac

# Convert size to bytes
case "$uboot_size_unit" in
    "mebibytes") uboot_size_bytes=$((uboot_size * 1024 * 1024)) ;;
    "kibibytes") uboot_size_bytes=$((uboot_size * 1024)) ;;
    "bytes") uboot_size_bytes=$uboot_size ;;
    *) echo "Error: Unknown size unit: $uboot_size_unit"; exit 1 ;;
esac

echo "Clearing uboot-env at offset ${uboot_offset_bytes} bytes, size ${uboot_size_bytes} bytes"
# Use skip blocks approach for BusyBox dd compatibility
uboot_offset_blocks=$((uboot_offset_bytes / 512))
uboot_size_blocks=$(((uboot_size_bytes + 511) / 512))  # Round up
if ! dd if=/dev/zero of="${rpi_block_device}" bs=512 seek=${uboot_offset_blocks} count=${uboot_size_blocks} 2>/dev/null; then
    echo "Error: Failed to clear uboot-env partition"
    exit 1
fi

echo "Writing system image to rpi..."

# Ensure device is not mounted and accessible
if mount | grep -q "${rpi_block_device}"; then
    echo "Unmounting any mounted partitions on ${rpi_block_device}..."
    if ! umount "${rpi_block_device}"* 2>/dev/null; then
        echo "Error: Failed to unmount partitions on ${rpi_block_device}"
        exit 1
    fi
fi

# Brief wait to ensure device is ready
sleep 2

# Verify device is accessible before fwup
if ! dd if="${rpi_block_device}" of=/dev/null bs=512 count=1 2>/dev/null; then
    echo "Error: Device ${rpi_block_device} is not accessible for read/write operations"
    exit 1
fi

if ! fwup -a -u -i "${archive_file}" -d "${rpi_block_device}" -t complete 2>&1; then
    echo "Error: fwup failed to write system image"
    exit 1
fi

echo "System image successfully written to rpi!"
echo "Please disconnect the USB cable and power cycle the device in normal boot mode."
echo "Remove any boot mode jumpers or reset boot switches and ensure the device boots from eMMC."

exit 0
