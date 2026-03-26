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

# When USB passthrough is unavailable (Docker Desktop on macOS/Windows),
# produce a disk image for host-side burning instead of flashing directly.
if [ "${AVOCADO_USB_PASSTHROUGH:-1}" = "0" ]; then
    echo "=========================================="
    echo "Docker Desktop detected - no device access"
    echo "Producing disk image for host-side burning"
    echo "=========================================="

    if [ -z "${AVOCADO_PROVISION_OUT:-}" ]; then
        echo "Error: AVOCADO_PROVISION_OUT must be set when USB passthrough is unavailable"
        exit 1
    fi

    mkdir -p "$AVOCADO_PROVISION_OUT"

    echo "Creating raw disk image from archive..."
    fwup -a -i "${archive_file}" -d "${archive_image}" -t complete

    echo "Copying image to provision output..."
    cp -v "${archive_image}" "$AVOCADO_PROVISION_OUT/"

    # Write result metadata for CLI host-side burning
    cat > "$AVOCADO_PROVISION_OUT/.provision-result.json" <<RESULT_EOF
{
  "host_action": "burn_removable",
  "image": "$(basename "${archive_image}")"
}
RESULT_EOF

    echo "Disk image ready for host-side SD card burning."
    exit 0
fi

echo "=========================================="
echo "Avocado SD Card Provisioning Tool (iMX)"
echo "=========================================="
echo ""
echo "This tool will write the Avocado system image to an SD card."
echo ""

# =============================================================================
# Device selection helper
# =============================================================================

get_device_info() {
    local dev_path="$1"
    local dev_name
    dev_name=$(basename "$dev_path")
    local sysblock="/sys/block/${dev_name}"
    local vendor="" model=""
    if [[ -d "$sysblock" ]]; then
        vendor=$(cat "$sysblock/device/vendor" 2>/dev/null | xargs || true)
        model=$(cat "$sysblock/device/model" 2>/dev/null | xargs || true)
    fi
    echo "${vendor:+$vendor }${model:-unknown}"
}

# Identify boot volume so we never offer to overwrite it
root_dev=""
if [[ -f /proc/mounts ]]; then
    root_mount=$(awk '$2 == "/" {print $1; exit}' /proc/mounts)
    if [[ -n "$root_mount" && -b "$root_mount" ]]; then
        root_dev=$(echo "$root_mount" | sed -E 's/p?[0-9]+$//')
        if [[ "$root_dev" == "$root_mount" ]]; then
            root_dev=$(echo "$root_mount" | sed 's/[0-9]*$//')
        fi
    fi
fi

# =============================================================================
# Non-interactive mode: AVOCADO_PROVISION_DEVICE
# =============================================================================

sd_block_device=""

if [[ -n "${AVOCADO_PROVISION_DEVICE:-}" ]]; then
    echo "Non-interactive mode: AVOCADO_PROVISION_DEVICE=${AVOCADO_PROVISION_DEVICE}"
    echo ""

    if [[ ! -b "$AVOCADO_PROVISION_DEVICE" ]]; then
        echo "Error: ${AVOCADO_PROVISION_DEVICE} is not a valid block device"
        exit 1
    fi

    if [[ -n "$root_dev" && "$AVOCADO_PROVISION_DEVICE" == "$root_dev" ]]; then
        echo "Error: ${AVOCADO_PROVISION_DEVICE} is the boot volume -- refusing to overwrite"
        exit 1
    fi

    sd_block_device="$AVOCADO_PROVISION_DEVICE"
    echo "Using device: $sd_block_device ($(get_device_info "$sd_block_device"))"
else
    # =============================================================================
    # Interactive mode: list available devices, let user select
    # =============================================================================

    echo "Detecting available storage devices..."
    echo ""

    fwup_output=$(fwup -D 2>/dev/null || true)

    device_paths=()
    device_sizes=()

    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        dev_path="${line%,*}"
        dev_size="${line#*,}"

        # Filter out boot volume
        if [[ -n "$root_dev" && "$dev_path" == "$root_dev" ]]; then
            continue
        fi

        device_paths+=("$dev_path")
        device_sizes+=("$dev_size")
    done <<< "$fwup_output"

    if [[ ${#device_paths[@]} -eq 0 ]]; then
        echo "No removable storage devices detected."
        echo ""
        echo "Is your SD card inserted? Ensure the SD card reader is connected"
        echo "and the device is visible to the container."
        echo ""
        echo "Diagnostic — raw fwup -D output:"
        fwup -D 2>/dev/null || echo "  (fwup -D returned an error)"
        exit 1
    fi

    echo "--- Available storage devices ---"
    echo ""
    for i in "${!device_paths[@]}"; do
        dev_path="${device_paths[$i]}"
        dev_size="${device_sizes[$i]}"
        size_gib=$(echo "scale=1; $dev_size / 1073741824" | bc -l 2>/dev/null || echo "?")
        info=$(get_device_info "$dev_path")
        printf "  %-16s %6s GiB   %s\n" "$dev_path" "$size_gib" "$info"
    done

    if [[ -n "$root_dev" ]]; then
        echo ""
        echo "  (boot volume ${root_dev} is hidden)"
    fi
    echo ""

    if [[ ${#device_paths[@]} -eq 1 ]]; then
        sd_block_device="${device_paths[0]}"
        read -p "Use ${sd_block_device}? (y/N): " -r
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Operation cancelled by user"
            exit 1
        fi
    else
        read -p "Enter the target device path (e.g. /dev/sdX): " -r sd_block_device

        if [[ -z "$sd_block_device" ]]; then
            echo "Error: No device specified"
            exit 1
        fi

        if [[ ! -b "$sd_block_device" ]]; then
            echo "Error: ${sd_block_device} is not a valid block device"
            exit 1
        fi

        if [[ -n "$root_dev" && "$sd_block_device" == "$root_dev" ]]; then
            echo "Error: ${sd_block_device} is the boot volume -- refusing to overwrite"
            exit 1
        fi
    fi
fi

# =============================================================================
# Confirm and write
# =============================================================================

sd_device_size_bytes=$(blockdev --getsize64 "$sd_block_device" 2>/dev/null || echo "unknown")
if [[ "$sd_device_size_bytes" != "unknown" ]]; then
    device_size_gib_decimal=$(echo "scale=2; $sd_device_size_bytes / 1073741824" | bc -l 2>/dev/null || echo "?")
else
    device_size_gib_decimal="unknown"
fi
device_info=$(get_device_info "$sd_block_device")

echo ""
echo "Target SD card:"
echo "  Device: $sd_block_device"
echo "  Size:   ${device_size_gib_decimal} GiB"
echo "  Info:   $device_info"
echo ""

if [[ -z "${AVOCADO_PROVISION_DEVICE:-}" ]]; then
    echo "WARNING: This will completely overwrite ${sd_block_device}!"
    echo "All existing data on this SD card will be lost."
    echo ""
    read -p "Are you sure you want to continue? (y/N): " -r
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Operation cancelled by user"
        exit 1
    fi
fi

echo "Proceeding with firmware write..."

# Unmount any mounted partitions on the target device
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
