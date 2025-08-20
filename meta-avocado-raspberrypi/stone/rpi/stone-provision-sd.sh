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

archive_image="${archive_file%%.*}.img"

echo "=========================================="
echo "Avocado SD Card Provisioning Tool"
echo "=========================================="
echo ""
echo "This tool will write the Avocado system image to an SD card."
echo "Make sure you have an SD card ready for programming."
echo ""

# Record existing block devices before inserting SD card
echo "Recording existing block devices..."
existing_devices=()
existing_fwup_devices=$(fwup -D 2>/dev/null | grep "^/dev/sd" || true)
for device_entry in $existing_fwup_devices; do
    device_path="${device_entry%,*}"
    device_name=$(basename "$device_path")
    existing_devices+=("$device_name")
done
if [[ ${#existing_devices[@]} -eq 0 ]]; then
    echo "Existing devices: none"
else
    echo "Existing devices: ${existing_devices[*]}"
fi

echo ""
read -p "Please insert your SD card and press Enter to continue..." -r

echo "Waiting for new mass storage device to be detected..."

# Wait for new mass storage device to appear
STORAGE_TIMEOUT=60
storage_start_time=$(date +%s)
sd_block_device=""
last_dot_time=0

while [[ -z "$sd_block_device" ]]; do
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
            
            # Skip devices that existed before SD card insertion
            device_is_new=true
            for existing_dev in "${existing_devices[@]}"; do
                if [[ "$device_name" == "$existing_dev" ]]; then
                    device_is_new=false
                    break
                fi
            done
            
            if [[ "$device_is_new" == "true" ]]; then
                # Use the first new device fwup detects
                sd_block_device="$device_path"
                sd_device_size_bytes="$device_size_bytes"
                echo "Found new mass storage device: $sd_block_device"
                break
            fi
        done
    fi
    
    # Check timeout
    now=$(date +%s)
    if (( now - storage_start_time >= STORAGE_TIMEOUT )); then
        echo ""  # New line after progress dots
        echo "Timed out after $STORAGE_TIMEOUT seconds waiting for SD card"
        echo "Diagnostic information:"
        echo "Block devices currently detected by fwup:"
        current_fwup_devices=$(fwup -D 2>/dev/null | grep "^/dev/sd" || true)
        if [[ -n "$current_fwup_devices" ]]; then
            for device_entry in $current_fwup_devices; do
                device_path="${device_entry%,*}"
                device_size="${device_entry#*,}"
                device_name=$(basename "$device_path")
                echo "  Device $device_name: $device_path (${device_size} bytes)"
            done
        else
            echo "  No devices detected by fwup -D"
        fi
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
    if [[ -b "$sd_block_device" ]]; then
        # Try a simple read test first
        if timeout 2 dd if="$sd_block_device" of=/dev/null bs=512 count=1 2>/dev/null; then
            device_ready=true
            echo ""  # New line after progress dots
            echo "Block device is ready for access"
            break
        else
            # If dd fails, check if it's just a permission issue by testing file existence
            if [[ -r "$sd_block_device" ]]; then
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
        echo "Device status: block device exists: $([[ -b "$sd_block_device" ]] && echo "yes" || echo "no")"
        echo "Device status: readable: $([[ -r "$sd_block_device" ]] && echo "yes" || echo "no")"
        echo "Proceeding anyway - device may be ready despite timeout"
        break
    fi
    
    echo -n "."
    sleep 0.5
done

# Ensure we actually found a device
if [[ -z "$sd_block_device" ]]; then
    echo "Error: No new SD card was detected"
    exit 1
fi

# Calculate device size in GiB
device_size_gib=$((sd_device_size_bytes / 1024 / 1024 / 1024))
device_size_gib_decimal=$(echo "scale=2; $sd_device_size_bytes / 1024 / 1024 / 1024" | bc -l 2>/dev/null || echo "$device_size_gib")

echo "SD card successfully detected:"
echo "  Device: $sd_block_device"
echo "  Size: ${device_size_gib_decimal} GiB (${sd_device_size_bytes} bytes)"

# Get device vendor/model info if available
block_dev="/sys/block/$(basename "$sd_block_device")"
if [[ -d "$block_dev" ]]; then
    vendor_file="$block_dev/device/vendor"
    model_file="$block_dev/device/model"
    if [[ -f "$vendor_file" && -f "$model_file" ]]; then
        vendor=$(cat "$vendor_file" 2>/dev/null | xargs || echo "unknown")
        model=$(cat "$model_file" 2>/dev/null | xargs || echo "unknown")
        echo "  Vendor: $vendor"
        echo "  Model: $model"
    fi
fi

echo ""
echo "WARNING: This will completely overwrite the device $sd_block_device!"
echo "All existing data on this ${device_size_gib_decimal} GiB SD card will be lost."
echo ""

read -p "Are you sure you want to continue? (y/N): " -r

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Operation cancelled by user"
    exit 1
fi

echo "User confirmed. Proceeding with firmware write..."

# Ensure device is not mounted and accessible
if mount | grep -q "${sd_block_device}"; then
    echo "Unmounting any mounted partitions on ${sd_block_device}..."
    if ! umount "${sd_block_device}"* 2>/dev/null; then
        echo "Error: Failed to unmount partitions on ${sd_block_device}"
        exit 1
    fi
fi

# Brief wait to ensure device is ready
sleep 2

# Verify device is accessible before fwup
if ! dd if="${sd_block_device}" of=/dev/null bs=512 count=1 2>/dev/null; then
    echo "Error: Device ${sd_block_device} is not accessible for read/write operations"
    exit 1
fi

echo "Writing system image to SD card..."

if ! fwup -a -u -i "${archive_file}" -d "${sd_block_device}" -t complete 2>&1; then
    echo "Error: fwup failed to write system image"
    exit 1
fi

echo "System image successfully written to SD card!"
echo "You can now safely remove the SD card and use it to boot your device."

exit 0
