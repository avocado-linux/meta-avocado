#!/usr/bin/env bash

# Common rpiboot functions for RPi USB provisioning scripts.
# Source this file from stone-provision-usb*.sh scripts.
#
# Provides:
#   wait_for_rpiboot_device   - detect RPi in USB boot mode
#   record_existing_devices   - snapshot current block devices
#   find_rpiboot              - locate rpiboot binary and mass-storage-gadget
#   run_rpiboot               - put RPi into mass storage mode
#   wait_for_mass_storage     - wait for new block device to appear
#   wait_for_device_ready     - ensure block device is accessible
#
# After sourcing, the following variables are set by the functions:
#   rpi_block_device          - path to the detected block device
#   rpi_device_size_bytes     - size of the block device in bytes

VID=0a5c
# Supported boot device PIDs: BCM2711 (Pi4) and BCM2712 (Pi5)
PIDS=("2711" "2712")

# Wait for RPi to appear in USB boot mode.
# Args: $1 = timeout in seconds (default 20)
wait_for_rpiboot_device() {
    local timeout="${1:-20}"
    local start_time last_dot_time now
    start_time=$(date +%s)
    last_dot_time=0

    echo "Waiting for rpi boot device to be detected..."

    while :; do
        now=$(date +%s)
        if (( now - last_dot_time >= 2 )); then
            echo -n "."
            last_dot_time=$now
        fi
        for d in /sys/bus/usb/devices/*; do
            [[ -f "$d/idVendor" && -f "$d/idProduct" ]] || continue
            local device_vid device_pid
            device_vid=$(<"$d/idVendor")
            device_pid=$(<"$d/idProduct")
            if [[ "$device_vid" == "$VID" ]]; then
                for pid in "${PIDS[@]}"; do
                    if [[ "$device_pid" == "$pid" ]]; then
                        echo ""
                        echo "rpi boot device detected at $(basename "$d") (${device_vid}:${device_pid})"
                        return 0
                    fi
                done
            fi
        done

        now=$(date +%s)
        if (( now - start_time >= timeout )); then
            echo ""
            echo "Timed out after $timeout seconds waiting for rpi boot device"
            return 1
        fi

        sleep 0.5
    done
}

# Record existing block devices before enabling mass storage mode.
# Sets global array: existing_devices
record_existing_devices() {
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
}

# Find rpiboot binary and mass-storage-gadget path.
# Sets globals: rpiboot_path, mass_storage_gadget_path
find_rpiboot() {
    rpiboot_path=$(which rpiboot)
    if [[ -z "$rpiboot_path" ]]; then
        echo "Error: rpiboot not found in PATH"
        return 1
    fi

    local sysroot_prefix
    if [[ "$rpiboot_path" =~ ^(.*)/usr/ ]]; then
        sysroot_prefix="${BASH_REMATCH[1]}"
    else
        echo "Error: Could not determine sysroot prefix from rpiboot path: $rpiboot_path"
        return 1
    fi

    mass_storage_gadget_path="${sysroot_prefix}/usr/share/rpiboot/mass-storage-gadget64"

    if [[ ! -d "$mass_storage_gadget_path" ]]; then
        echo "Error: mass-storage-gadget64 directory not found at: $mass_storage_gadget_path"
        return 1
    fi

    echo "Using rpiboot at: $rpiboot_path"
    echo "Using mass-storage-gadget64 at: $mass_storage_gadget_path"
}

# Execute rpiboot to put the RPi into mass storage mode.
# Requires: rpiboot_path, mass_storage_gadget_path (from find_rpiboot)
run_rpiboot() {
    echo "Executing rpiboot to enable mass storage mode..."
    if ! "$rpiboot_path" -d "$mass_storage_gadget_path"; then
        echo "Error: rpiboot failed to execute"
        return 1
    fi
}

# Wait for RPi mass storage block device to appear.
# Requires: existing_devices array (from record_existing_devices)
# Sets globals: rpi_block_device, rpi_device_size_bytes
# Args: $1 = timeout in seconds (default 60)
wait_for_mass_storage() {
    local timeout="${1:-60}"
    local start_time last_dot_time now
    start_time=$(date +%s)
    last_dot_time=0
    rpi_block_device=""
    rpi_device_size_bytes=""

    echo "Waiting for rpi to appear as mass storage device..."

    while [[ -z "$rpi_block_device" ]]; do
        now=$(date +%s)
        if (( now - last_dot_time >= 2 )); then
            echo -n "."
            last_dot_time=$now
        fi

        local available_devices
        available_devices=$(fwup -D 2>/dev/null | grep "^/dev/sd" || true)

        if [[ -n "$available_devices" ]]; then
            echo ""

            for device_entry in $available_devices; do
                local device_path device_size_bytes device_name device_is_new
                device_path="${device_entry%,*}"
                device_size_bytes="${device_entry#*,}"
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
                    rpi_device_size_bytes="$device_size_bytes"
                    echo "Found new mass storage device: $rpi_block_device"
                    break
                fi
            done
        fi

        now=$(date +%s)
        if (( now - start_time >= timeout )); then
            echo ""
            echo "Timed out after $timeout seconds waiting for RPi mass storage device"
            echo "Diagnostic information:"
            echo "USB devices currently detected:"
            for d in /sys/bus/usb/devices/*; do
                [[ -f "$d/idVendor" && -f "$d/idProduct" ]] || continue
                local vid pid
                vid=$(<"$d/idVendor")
                pid=$(<"$d/idProduct")
                echo "  USB device $(basename "$d"): $vid:$pid"
            done
            echo "Block devices currently present:"
            for block_dev in /sys/block/sd*; do
                [[ -d "$block_dev" ]] || continue
                local dn vendor model
                dn=$(basename "$block_dev")
                if [[ -f "$block_dev/device/vendor" && -f "$block_dev/device/model" ]]; then
                    vendor=$(cat "$block_dev/device/vendor" 2>/dev/null | xargs)
                    model=$(cat "$block_dev/device/model" 2>/dev/null | xargs)
                    echo "  Block device $dn: vendor='$vendor' model='$model'"
                else
                    echo "  Block device $dn: no vendor/model info"
                fi
            done
            return 1
        fi

        sleep 1
    done
}

# Wait for the block device to be fully accessible.
# Requires: rpi_block_device (from wait_for_mass_storage)
# Args: $1 = timeout in seconds (default 15)
wait_for_device_ready() {
    local timeout="${1:-15}"
    local start_time now device_ready
    start_time=$(date +%s)
    device_ready=false

    echo "Waiting for block device to be ready for access..."

    while [[ "$device_ready" == "false" ]]; do
        if [[ -b "$rpi_block_device" ]]; then
            if timeout 2 dd if="$rpi_block_device" of=/dev/null bs=512 count=1 2>/dev/null; then
                device_ready=true
                echo ""
                echo "Block device is ready for access"
                break
            elif [[ -r "$rpi_block_device" ]]; then
                echo ""
                echo "Block device exists and is readable, proceeding..."
                device_ready=true
                break
            fi
        fi

        now=$(date +%s)
        if (( now - start_time >= timeout )); then
            echo ""
            echo "Device status: block device exists: $([[ -b "$rpi_block_device" ]] && echo "yes" || echo "no")"
            echo "Device status: readable: $([[ -r "$rpi_block_device" ]] && echo "yes" || echo "no")"
            echo "Proceeding anyway - device may be ready despite timeout"
            break
        fi

        echo -n "."
        sleep 0.5
    done
}

# Print device info and prompt for confirmation.
# Requires: rpi_block_device, rpi_device_size_bytes
confirm_device_write() {
    local device_size_gib device_size_gib_decimal
    device_size_gib=$((rpi_device_size_bytes / 1024 / 1024 / 1024))
    device_size_gib_decimal=$(echo "scale=2; $rpi_device_size_bytes / 1024 / 1024 / 1024" | bc -l 2>/dev/null || echo "$device_size_gib")

    echo "rpi successfully ready as mass storage device:"
    echo "  Device: $rpi_block_device"
    echo "  Size: ${device_size_gib_decimal} GiB (${rpi_device_size_bytes} bytes)"

    local block_dev="/sys/block/$(basename "$rpi_block_device")"
    if [[ -d "$block_dev" ]]; then
        local vendor_file="$block_dev/device/vendor"
        local model_file="$block_dev/device/model"
        if [[ -f "$vendor_file" && -f "$model_file" ]]; then
            local vendor model
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
        return 1
    fi

    echo "User confirmed. Proceeding with firmware write..."
}

# Full rpiboot flow: detect -> record -> find -> boot -> wait -> ready
# Sets: rpi_block_device, rpi_device_size_bytes
rpiboot_detect_and_expose() {
    wait_for_rpiboot_device || exit 1
    record_existing_devices
    find_rpiboot || exit 1
    run_rpiboot || exit 1
    wait_for_mass_storage || exit 1
    wait_for_device_ready

    if [[ -z "$rpi_block_device" ]]; then
        echo "Error: No new RPi mass storage device was detected"
        exit 1
    fi
}
