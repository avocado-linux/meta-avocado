#!/bin/bash
# -*- mode: shell-script; indent-tabs-mode: nil; sh-basic-offset: 4; -*-
#
# initrd-flash.sh - Initrd-based flashing for Tegra devices
#
# Supports both T234 (Orin) and T264 (Thor) SoCs:
#   T234: Uses tegraflash.py-based flow with USB mass storage
#   T264: Uses unified flash flow (create_bsp_images.py)
#
# Container-aware: uses sysfs-based device detection and direct mount
# instead of udisksctl/udevadm, which are unavailable in containers.

set -o pipefail

me=$(basename "$0")
here=$(readlink -f $(dirname "$0"))

declare -A DEFAULTS

usage() {
    cat <<EOF
Usage:
  $me [options]

Options:
  -D|--debug            Enable debug logging when running flash script
  -h|--help             Displays this usage information
  --external-only       Write only the external storage device
  --erase-nvme          Erase NVME drive during flashing (T234 only)
  --erase-emmc          Erase eMMC drive during flashing
  --erase-only          Only erase specified drives, do not write partitions
  -k|--partition NAME   Write only the specified partition (T264 only)
  --qspi-only           Write only the QSPI flash (boot firmware)
  --usb-instance        USB instance of Jetson device

Options passed through to flash helper:
  -u                    PKC key file for signing
  -v                    SBK key file for signing

Note that --external-only, --qspi-only, and --partition are mutually
exclusive.

EOF
}

# The build must generate these environment settings
if [ ! -e .env.initrd-flash ]; then
    echo "Missing environment settings" >&2
    exit 1
fi

. .env.initrd-flash

# The .presigning-vars file is generated when binaries
# are signed during the build
PRESIGNED=
if [ -e .presigning-vars ]; then
    . .presigning-vars
    PRESIGNED=yes
fi

usb_instance=
instance_args=
keyfile=
sbk_keyfile=
skip_bootloader=0
qspi_only=0
partition_name=
early_final_status=0
erase_nvme=0
erase_emmc=0
erase_only=0
check_usb_instance="${TEGRAFLASH_CHECK_USB_INSTANCE:-no}"
uniflash_flags=""

ARGS=$(getopt -n $(basename "$0") -l "usb-instance:,help,skip-bootloader,external-only,qspi-only,partition,debug,erase-nvme,erase-emmc,erase-only" -o "u:v:k:hD" -- "$@")
if [ $? -ne 0 ]; then
    usage >&2
    exit 1
fi
eval set -- "$ARGS"
unset ARGS

while true; do
    case "$1" in
        --usb-instance)
            usb_instance="$2"
            shift 2
            ;;
        --skip-bootloader|--external-only)
            skip_bootloader=1
            shift
            if [ $qspi_only -eq 1 -o -n "$partition_name" ]; then
                echo "ERR: specify only one of --external-only, --qspi-only, --partition" >&2
                exit 1
            fi
            ;;
        --qspi-only)
            qspi_only=1
            shift
            if [ $skip_bootloader -eq 1 -o -n "$partition_name" ]; then
                echo "ERR: specify only one of --external-only, --qspi-only, --partition" >&2
                exit 1
            fi
            ;;
        --erase-nvme)
            erase_nvme=1
            shift
            ;;
        --erase-emmc)
            erase_emmc=1
            shift
            ;;
        --erase-only)
            erase_only=1
            shift
            ;;
        -u)
            keyfile="$2"
            shift 2
            ;;
        -v)
            sbk_keyfile="$2"
            shift 2
            ;;
        -k|--partition)
            partition_name="$2"
            shift 2
            if [ $skip_bootloader -eq 1 -o $qspi_only -eq 1 ]; then
                echo "ERR: specify only one of --external-only, --qspi-only, --partition" >&2
                exit 1
            fi
            uniflash_flags="$uniflash_flags -u $partition_name"
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        -D|--debug)
            uniflash_flags="$uniflash_flags -D"
            shift
            ;;
        --)
            shift
            break
            ;;
        *)
            echo "Error processing options" >&2
            usage
            exit 1
            ;;
    esac
done

if [ -n "$PRESIGNED" ]; then
    if [ -n "$keyfile" -o -n "$sbk_keyfile" ]; then
        echo "WARN: binaries already signed; ignoring signing options" >&2
        keyfile=
        sbk_keyfile=
    fi
fi

wait_for_rcm() {
    "$here/find-jetson-usb" --wait "$usb_instance"
}

# Ask the avocado-vm-agent (running outside the SDK container, inside the
# avocado-vm) to perform a real USB disconnect/reconnect cycle by
# bouncing the device on the macOS host. Used when this script is running
# inside the avocado-vm and the Linux `authorized=0` toggle would be a
# no-op (vhci_hcd doesn't propagate it to the actual USB device).
#
# Returns 0 if the host completed the twiddle (status "ok" or "manual"),
# 1 otherwise (agent unreachable, response malformed, host gave up).
_twiddle_via_agent() {
    local usb_instance="$1"
    local sock="${AVOCADO_AGENT_SOCK:-}"

    if [ -z "$sock" ] || [ ! -S "$sock" ]; then
        return 1   # agent not available — caller falls back to sysfs path
    fi

    local req
    req=$(printf '{"loc_hint":"%s"}' "$usb_instance")
    local resp=""

    # Two transports — prefer nc -U for terseness, fall back to python3.
    # Either should be available in the SDK container. 130s overall
    # timeout: the host has a 120s waiter for user replug, +10s slack.
    if command -v nc >/dev/null 2>&1; then
        resp=$(printf "%s\n" "$req" | timeout 130 nc -U "$sock" 2>/dev/null) || return 1
    elif command -v python3 >/dev/null 2>&1; then
        resp=$(REQ="$req" python3 -c "
import os, socket, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(130)
s.connect('$sock')
s.sendall((os.environ['REQ'] + '\n').encode())
data = b''
while True:
    chunk = s.recv(4096)
    if not chunk: break
    data += chunk
    if b'\n' in chunk: break
sys.stdout.write(data.decode(errors='replace'))
") || return 1
    else
        echo "WARN: agent transport unavailable (no nc, no python3); cannot reach $sock" >&2
        return 1
    fi

    case "$resp" in
        *'"status":"ok"'*|*'"status":"manual"'*)
            echo "Agent twiddle succeeded: $resp" >&2
            return 0
            ;;
        *)
            echo "WARN: agent twiddle returned non-success: $resp" >&2
            return 1
            ;;
    esac
}

# Shared function to disconnect USB device by toggling authorized attribute
# (or, when AVOCADO_AGENT_SOCK is set, by asking the avocado-vm-agent to
# do a real disconnect/reconnect cycle on the host — which is the only
# thing that advances staging-protocol firmwares like the Jetson MB1→MB2
# transition when the script runs inside the avocado-vm).
#
# Parameters:
#   $1: usb_instance - The USB bus path (e.g., "3-1")
#   $2: session_id (optional) - If provided, will rescan to find current USB instance
disconnect_usb_device() {
    local usb_instance="$1"
    local sessid="$2"

    # If session ID is provided, rescan to find current device and USB instance.
    # This handles the case where the device reconnected with a different USB
    # path. When the device is *gone* entirely, the disconnect is already in
    # effect — return success without re-issuing a twiddle. This is the
    # idempotency contract that lets generate_flash_package call us a second
    # time (after unmount_and_release already cycled the device) without
    # accidentally blocking on a 120s replug-waiter for a phantom request.
    if [ -n "$sessid" ]; then
        echo "Rescanning for device with session ID $sessid..." >&2
        local current_dev=$(find_device_by_session "$sessid")
        if [ -n "$current_dev" ]; then
            local rescanned_instance=$(find_usb_instance_from_device "$current_dev")
            if [ -n "$rescanned_instance" ]; then
                echo "Device found at $current_dev with USB instance $rescanned_instance" >&2
                usb_instance="$rescanned_instance"
            else
                echo "WARN: Could not find USB instance for rescanned device $current_dev" >&2
            fi
        else
            echo "Device with session ID $sessid already gone — disconnect already in effect" >&2
            return 0
        fi
    fi

    if [ -z "$usb_instance" ]; then
        echo "WARN: No USB instance available for disconnect" >&2
        return 1
    fi

    # Prefer the agent-driven path when available. Falls through to the
    # sysfs toggle on any failure so this remains a non-breaking change
    # for non-avocado-vm contexts (bare Linux flashing, CI, etc).
    if _twiddle_via_agent "$usb_instance"; then
        echo "USB device $usb_instance twiddled via agent" >&2
        return 0
    fi

    local authorized_path="/sys/bus/usb/devices/$usb_instance/authorized"

    if [ ! -w "$authorized_path" ]; then
        echo "WARN: Cannot write to $authorized_path (device may not exist or path changed)" >&2
        return 1
    fi

    echo "Disconnecting USB device $usb_instance by toggling authorized..." >&2
    # Set authorized to 0 (disconnect)
    echo 0 > "$authorized_path" 2>/dev/null || {
        echo "ERR: Failed to deauthorize USB device $usb_instance" >&2
        return 1
    }

    # Wait a moment for the disconnect to be processed
    sleep 1

    # Set authorized back to 1 (reconnect) - path may no longer exist after deauthorization
    if [ -e "$authorized_path" ]; then
        echo 1 > "$authorized_path" 2>/dev/null || true
    fi

    echo "USB device $usb_instance disconnected and reconnected" >&2
    return 0
}

sign_binaries() {
    if [ -n "$PRESIGNED" ]; then
	cp doflash.sh flash_signed.sh
	sed -i -e's,--cfg secureflash.xml,--cfg internal-secureflash.xml,g' flash_signed.sh
	cp secureflash.xml internal-secureflash.xml
	cp external-flash.xml.in external-secureflash.xml
	if ! copy_bootloader_files bootloader_staging; then
	    return 1
	fi
	if [ -e rcm-boot.sh ]; then
	    return 0
	fi
	if [ ! -e rcmboot_blob/rcmbootcmd.txt ]; then
	    echo "ERR: missing RCM boot blob in pre-signed binaries" >&2
	    return 1
	fi
	create_rcm_boot_script
	return 0
    fi

    if [ -z "$BOARDID" -o -z "$FAB" ]; then
	wait_for_rcm
    fi
    rm -rf rcmboot_blob
    if MACHINE=$MACHINE BOARDID=$BOARDID FAB=$FAB BOARDSKU=$BOARDSKU BOARDREV=$BOARDREV CHIPREV=$CHIPREV CHIP_SKU=$CHIP_SKU serial_number=$serial_number \
	      "$here/$FLASH_HELPER" --no-flash --sign -u "$keyfile" -v "$sbk_keyfile" $instance_args \
	      flash.xml.in $DTBFILE $EMMC_BCTS $ODMDATA $LNXFILE $ROOTFS_IMAGE; then
	cp flashcmd.txt flash_signed.sh
	sed -i -e's,--cfg secureflash.xml,--cfg internal-secureflash.xml,g' flash_signed.sh
	cp secureflash.xml internal-secureflash.xml
	cp external-flash.xml.in external-secureflash.xml
	create_rcm_boot_script
    else
	return 1
    fi
    if ! copy_bootloader_files bootloader_staging; then
	return 1
    fi
    if [ -e external-flash.xml.in ]; then
	if grep -q 'oem_sign="true"' external-flash.xml.in 2>/dev/null; then
	    . ./boardvars.sh
            if MACHINE=$MACHINE BOARDID=$BOARDID FAB=$FAB BOARDSKU=$BOARDSKU BOARDREV=$BOARDREV CHIPREV=$CHIPREV CHIP_SKU=$CHIP_SKU \
				"$here/$FLASH_HELPER" --no-flash --sign --external-device -u "$keyfile" -v "$sbk_keyfile" $instance_args \
				external-flash.xml.in $DTBFILE $EMMC_BCTS $ODMDATA $LNXFILE $ROOTFS_IMAGE; then
		mv secureflash.xml external-secureflash.xml
	    else
		return 1
	    fi
	else
	    cp external-flash.xml.in external-secureflash.xml
	fi
    fi
    return 0
}

prepare_for_rcm_boot() {
    :
}

run_rcm_boot() {
    if [ -z "$BR_CID" ]; then
	if ./rcm-boot.sh | tee rcm-boot.output; then
	    BR_CID=$(grep BR_CID: rcm-boot.output | cut -d: -f2)
	    return 0
	else
	    return 1
	fi
    fi
    ./rcm-boot.sh || return 1
}

# ===========================================================================
# Container-aware helper functions
# ===========================================================================

# Helper function to get device property from sysfs (replaces udevadm)
get_device_property() {
    local device="$1"
    local property="$2"
    local sysfs_path="/sys/block/$(basename "$device")"
    local result=""

    case "$property" in
        "ID_MODEL")
            # Try to get model from device/model or device/product
            if [ -r "$sysfs_path/device/model" ]; then
                result=$(cat "$sysfs_path/device/model" 2>/dev/null | tr -d ' \t\n\r')
            elif [ -r "$sysfs_path/device/product" ]; then
                result=$(cat "$sysfs_path/device/product" 2>/dev/null | tr -d ' \t\n\r')
            fi
            ;;
        "ID_VENDOR")
            # Try to get vendor from device/vendor
            if [ -r "$sysfs_path/device/vendor" ]; then
                result=$(cat "$sysfs_path/device/vendor" 2>/dev/null | tr -d ' \t\n\r')
            fi
            ;;
        "DEVPATH")
            # Get the device path by following symlinks in sysfs
            if [ -L "$sysfs_path" ]; then
                result=$(readlink -f "$sysfs_path" 2>/dev/null | sed 's|^/sys||')
            fi
            ;;
    esac

    echo "$result"
}

# Helper function to detect filesystem type
detect_filesystem() {
    local dev="$1"
    local fstype=""

    # First check if device is currently mounted using mount command
    fstype=$(mount | grep "^$dev " | awk '{print $5}' | head -1 2>/dev/null)
    if [ -n "$fstype" ]; then
        echo "$fstype"
        return 0
    fi

    # Try reading filesystem signature from the device
    if [ -r "$dev" ]; then
        # Check for FAT32 (most common for USB storage)
        local magic=$(dd if="$dev" bs=1 skip=82 count=8 2>/dev/null | tr -d '\0' | tr -d ' ')
        if [ "$magic" = "FAT32" ]; then
            echo "vfat"
            return 0
        fi

        # Check for FAT16/FAT12
        magic=$(dd if="$dev" bs=1 skip=54 count=8 2>/dev/null | tr -d '\0' | tr -d ' ')
        if [ "$magic" = "FAT16" ] || [ "$magic" = "FAT12" ]; then
            echo "vfat"
            return 0
        fi

        # Check for ext4 magic number
        magic=$(dd if="$dev" bs=1 skip=1080 count=2 2>/dev/null | hexdump -v -e '/1 "%02x"')
        if [ "$magic" = "53ef" ]; then
            echo "ext4"
            return 0
        fi

        # Try using file command if available (fallback)
        if command -v file >/dev/null 2>&1; then
            local file_output=$(file -s "$dev" 2>/dev/null)
            case "$file_output" in
                *"FAT"*|*"DOS/MBR"*) echo "vfat"; return 0 ;;
                *"ext4"*) echo "ext4"; return 0 ;;
                *"ext3"*) echo "ext3"; return 0 ;;
                *"ext2"*) echo "ext2"; return 0 ;;
            esac
        fi
    fi

    # Default fallback - most USB storage devices use FAT32
    echo "vfat"
}

# Helper function to find USB device instance (bus-devpath) from a block device
# Returns the USB path like "3-1" or "4-2.1"
find_usb_instance_from_device() {
    local dev="$1"
    local dev_name=$(basename "$dev")
    local sysfs_path="/sys/block/$dev_name"

    if [ ! -L "$sysfs_path/device" ]; then
        return 1
    fi

    # Walk up the device hierarchy to find the USB device
    local current_path=$(readlink -f "$sysfs_path/device" 2>/dev/null)
    while [ -n "$current_path" ] && [ "$current_path" != "/" ] && [ "$current_path" != "/sys" ]; do
        # Check if this is a USB device (has idVendor and idProduct)
        if [ -f "$current_path/idVendor" ] && [ -f "$current_path/idProduct" ]; then
            # Extract bus and device number from path (e.g., /sys/devices/pci0000:00/0000:00:14.0/usb2/2-10)
            local usb_path_info=$(basename "$current_path")
            if echo "$usb_path_info" | grep -q '^[0-9]\+-[0-9.]\+'; then
                echo "$usb_path_info"
                return 0
            fi
        fi
        current_path=$(dirname "$current_path")
    done

    return 1
}

# Helper function to find current device by session ID (derived from serial number)
# This is needed because devices can change their device node (/dev/sdX) and USB path
find_device_by_session() {
    local sessid="$1"

    if [ -z "$sessid" ]; then
        return 1
    fi

    # Scan all /dev/sd[a-z] devices to find one matching the session ID
    for candidate in /dev/sd[a-z]; do
        [ -b "$candidate" ] || continue
        local cand_model=$(get_device_property "$candidate" "ID_MODEL")
        if [ "$cand_model" = "$sessid" ]; then
            echo "$candidate"
            return 0
        fi
    done

    return 1
}

# Helper function to get current mounts for a device (container-friendly)
get_device_mounts() {
    local dev="$1"
    # Use mount command output instead of /proc/mounts
    # This works in containers and doesn't require /proc access
    mount | grep "^$dev " | awk '{print $3}' 2>/dev/null || true
}

# ===========================================================================
# Container-aware mount/unmount/USB-wait functions (chip-independent)
# ===========================================================================

mount_partition() {
    local dev="$1"
    local mnt_base="/tmp/usb_mount"
    local mnt_point="${mnt_base}_$$_$(basename "$dev")"
    local existing_mnt fstype

    # Check if device is already mounted and unmount all existing mounts
    local all_mounts=$(get_device_mounts "$dev")
    for mnt in $all_mounts; do
        if ! umount "$mnt" > /dev/null 2>&1; then
            echo "ERR: unmount $mnt on device $dev failed" >&2
            return 1
        fi
    done

    # Create mount point
    mkdir -p "$mnt_point"

    # Detect filesystem type
    fstype=$(detect_filesystem "$dev")

    # Try to mount with detected filesystem type
    if mount -t "$fstype" "$dev" "$mnt_point" 2>/dev/null; then
        echo "$mnt_point"
        return 0
    fi

    # If that fails, try without specifying filesystem type (let kernel auto-detect)
    if mount "$dev" "$mnt_point" 2>/dev/null; then
        echo "$mnt_point"
        return 0
    fi

    # If that fails, try common filesystem types
    for fs in vfat fat32 ext4 ext3 ext2; do
        if mount -t "$fs" "$dev" "$mnt_point" 2>/dev/null; then
            echo "$mnt_point"
            return 0
        fi
    done

    # Cleanup on failure
    rmdir "$mnt_point" 2>/dev/null
    echo ""
    return 1
}

unmount_and_release() {
    local mnt="$1"
    local dev="$2"

    # Unmount if mount point provided
    if [ -n "$mnt" ]; then
        if ! umount "$mnt" 2>/dev/null; then
            # Try force unmount, then lazy unmount as last resort
            umount -f "$mnt" 2>/dev/null || umount -l "$mnt" 2>/dev/null
        fi
        # Clean up mount point if it's one we created
        if echo "$mnt" | grep -q "^/tmp/usb_mount"; then
            rmdir "$mnt" 2>/dev/null
        fi
    fi

    # For device release, ensure all data is written
    if [ -n "$dev" ]; then
        sync

        # Try to flush device buffers using blockdev if available (container-friendly)
        if command -v blockdev >/dev/null 2>&1; then
            blockdev --flushbufs "$dev" 2>/dev/null || true
        fi

        # Use the reliable USB disconnect method via authorized toggle
        # Pass session_id to allow rescanning if device path changed
        if [ -n "$usb_instance" ]; then
            disconnect_usb_device "$usb_instance" "$session_id"
        fi
    fi

    return 0
}

wait_for_usb_storage() {
    local sessid="$1"
    local name="$2"
    local usbi="$3"
    local count=0
    local output candidate cand_model cand_vendor cand_devpath ok
    local fromname="${sessid:-${usbi}}"

    echo -n "Waiting for USB storage device $name from ${fromname:-target}..." >&2
    while [ -z "$output" ]; do
        for candidate in /dev/sd[a-z]; do
            [ -b "$candidate" ] || continue
            ok=
            if [ -n "$sessid" ]; then
                cand_model=$(get_device_property "$candidate" "ID_MODEL")
                if [ "$cand_model" = "$sessid" ]; then
                    ok=yes
                fi
            elif [ -n "$usbi" -a "$check_usb_instance" = "yes" ]; then
                cand_devpath=$(get_device_property "$candidate" "DEVPATH")
                if echo "$cand_devpath" | grep -q "/$usbi/" 2>/dev/null; then
                    ok=yes
                fi
            else
                ok=yes
            fi
            if [ "$ok" = "yes" ]; then
                cand_vendor=$(get_device_property "$candidate" "ID_VENDOR")
                if [ "$cand_vendor" = "$name" ]; then
                    echo "[$candidate]" >&2
                    output="$candidate"
                    break
                elif [ "$name" != "flashpkg" -a "$cand_vendor" = "flashpkg" ]; then
                    # This could happen if there was a failure on the device side
                    echo "[got flashpkg when expecting $name]" >&2
                    echo ""
                    early_final_status=1
                    return 1
                fi
            fi
        done
        if [ -z "$output" ]; then
            sleep 1
            count=$(expr $count \+ 1)
            if [ $count -ge 5 ]; then
                echo -n "." >&2
                count=0
            fi
        fi
    done
    echo "$output"
    return 0
}

# Wait for exported storage device with minimum size requirement
wait_for_exported_storage() {
    local sessid="$1"
    local name="$2"
    local usbi="$3"
    local min_size_mb="${4:-1000}"  # Minimum 1GB for external storage
    local timeout="${5:-120}"  # 2 minute timeout
    local count=0
    local output candidate cand_model cand_vendor cand_devpath ok device_size_mb
    local fromname="${sessid:-${usbi}}"
    local start_time=$(date +%s)

    echo -n "Waiting for exported storage device $name (min ${min_size_mb}MB) from ${fromname:-target}..." >&2
    while [ -z "$output" ]; do
        # Check timeout
        local current_time=$(date +%s)
        local elapsed=$((current_time - start_time))
        if [ $elapsed -ge $timeout ]; then
            echo "" >&2
            echo "ERR: Timeout waiting for exported storage device $name after ${timeout}s" >&2
            echo "Available devices:" >&2
            for candidate in /dev/sd[a-z]; do
                [ -b "$candidate" ] || continue
                local size_blocks=$(cat /sys/block/$(basename "$candidate")/size 2>/dev/null || echo "0")
                local size_mb=$((size_blocks / 2048))
                local vendor=$(get_device_property "$candidate" "ID_VENDOR")
                echo "  $candidate: ${size_mb}MB, vendor: $vendor" >&2
            done
            return 1
        fi
        for candidate in /dev/sd[a-z]; do
            [ -b "$candidate" ] || continue
            ok=
            if [ -n "$sessid" ]; then
                cand_model=$(get_device_property "$candidate" "ID_MODEL")
                if [ "$cand_model" = "$sessid" ]; then
                    ok=yes
                fi
            elif [ -n "$usbi" -a "$check_usb_instance" = "yes" ]; then
                cand_devpath=$(get_device_property "$candidate" "DEVPATH")
                if echo "$cand_devpath" | grep -q "/$usbi/" 2>/dev/null; then
                    ok=yes
                fi
            else
                ok=yes
            fi
            if [ "$ok" = "yes" ]; then
                cand_vendor=$(get_device_property "$candidate" "ID_VENDOR")
                # Check device size to ensure it's the exported storage, not the command device
                local device_size_blocks=$(cat /sys/block/$(basename "$candidate")/size 2>/dev/null || echo "0")
                device_size_mb=$((device_size_blocks / 2048))  # Convert 512-byte blocks to MB

                if [ "$cand_vendor" = "$name" ] || [ "$name" != "flashpkg" -a "$cand_vendor" = "flashpkg" ]; then
                    if [ $device_size_mb -ge $min_size_mb ]; then
                        echo "[$candidate] (${device_size_mb}MB, vendor: $cand_vendor)" >&2
                        output="$candidate"
                        break
                    else
                        echo -n "[${candidate}:${device_size_mb}MB<${min_size_mb}MB]" >&2
                    fi
                elif [ $count -gt 0 ] && [ $(expr $count % 20) -eq 0 ]; then
                    # Periodically show what devices we're seeing for debugging
                    echo -n "[${candidate}:${device_size_mb}MB,vendor:$cand_vendor]" >&2
                fi
            fi
        done
        if [ -z "$output" ]; then
            sleep 1
            count=$(expr $count \+ 1)
            if [ $count -ge 5 ]; then
                echo -n "." >&2
                count=0
            fi
        fi
    done
    echo "$output"
    return 0
}

# ===========================================================================
# T234 (Orin) functions - tegraflash.py-based flow with USB mass storage
# ===========================================================================

copy_signed_binaries() {
    local signdir="${1:-signed}"
    local xmlfile="${2:-flash.xml.tmp}"
    local destdir="${3:-.}"
    local blksize partnumber partname partsize partfile partguid parttype partfilltoend
    local line

    while read line; do
        eval "$line"
        [ -n "$partfile" ] || continue
        if [ ! -e "$signdir/$partfile" ]; then
            if [ ! -e "$destdir/$partfile" ] && ! echo "$partfile" | grep -q "FILE"; then
                echo "ERR: could not copy $partfile from $signdir" >&2
                return 1
            fi
        else
            cp "$signdir/$partfile" "$destdir"
        fi
    done < <("$here/nvflashxmlparse" -t boot "$signdir/$xmlfile"; "$here/nvflashxmlparse" -t rootfs "$signdir/$xmlfile")
}

create_rcm_boot_script() {
    ln -sf "$here/tegrarcm_v2" rcmboot_blob/
    cat > rcm-boot.sh <<EOF
oldwd="\$PWD"
cd rcmboot_blob
EOF
    cat rcmboot_blob/rcmbootcmd.txt >> rcm-boot.sh
    cat >> rcm-boot.sh <<EOF
cd "\$oldwd"
EOF
    chmod +x rcm-boot.sh
}

sign_binaries_t234() {
    if [ -n "$PRESIGNED" ]; then
        cp doflash.sh flash_signed.sh
        sed -i -e's,--cfg secureflash.xml,--cfg internal-secureflash.xml,g' flash_signed.sh
        cp secureflash.xml internal-secureflash.xml
        if [ -e external-flash.xml.in ]; then
            cp external-flash.xml.in external-secureflash.xml
        fi
        if ! copy_bootloader_files_t234 bootloader_staging; then
            return 1
        fi
        if [ -e rcm-boot.sh ]; then
            return 0
        fi
        if [ ! -e rcmboot_blob/rcmbootcmd.txt ]; then
            echo "ERR: missing RCM boot blob in pre-signed binaries" >&2
            return 1
        fi
        create_rcm_boot_script
        return 0
    fi

    if [ -z "$BOARDID" -o -z "$FAB" ]; then
        wait_for_rcm
    fi
    rm -rf rcmboot_blob
    if MACHINE=$MACHINE BOARDID=$BOARDID FAB=$FAB BOARDSKU=$BOARDSKU BOARDREV=$BOARDREV CHIPREV=$CHIPREV CHIP_SKU=$CHIP_SKU serial_number=$serial_number \
              "$here/$FLASH_HELPER" --no-flash --sign -u "$keyfile" -v "$sbk_keyfile" $instance_args \
              flash.xml.in $DTBFILE $EMC_BCT $ODMDATA $LNXFILE $ROOTFS_IMAGE; then
        cp flashcmd.txt flash_signed.sh
        sed -i -e's,--cfg secureflash.xml,--cfg internal-secureflash.xml,g' flash_signed.sh
        cp secureflash.xml internal-secureflash.xml
        if [ -e external-flash.xml.in ]; then
            cp external-flash.xml.in external-secureflash.xml
        fi
        create_rcm_boot_script
    else
        return 1
    fi
    if ! copy_bootloader_files_t234 bootloader_staging; then
        return 1
    fi
    if [ -e external-flash.xml.in ]; then
        if grep -q 'oem_sign="true"' external-flash.xml.in 2>/dev/null; then
            . ./boardvars.sh
            if MACHINE=$MACHINE BOARDID=$BOARDID FAB=$FAB BOARDSKU=$BOARDSKU BOARDREV=$BOARDREV CHIPREV=$CHIPREV CHIP_SKU=$CHIP_SKU \
                            "$here/$FLASH_HELPER" --no-flash --sign --external-device -u "$keyfile" -v "$sbk_keyfile" $instance_args \
                            external-flash.xml.in $DTBFILE $EMC_BCT $ODMDATA $LNXFILE $ROOTFS_IMAGE; then
                mv secureflash.xml external-secureflash.xml
            else
                return 1
            fi
        else
            cp external-flash.xml.in external-secureflash.xml
        fi
    fi
    return 0
}

run_rcm_boot_t234() {
    if [ -z "$BR_CID" ]; then
        if ./rcm-boot.sh | tee rcm-boot.output; then
            BR_CID=$(grep BR_CID: rcm-boot.output | cut -d: -f2)
            return 0
        else
            return 1
        fi
    fi
    ./rcm-boot.sh || return 1
}

copy_bootloader_files_t234() {
    local dest="$1"
    local partnumber partloc partname start_location partsize partfile partattrs partsha
    local devnum instnum
    local is_spi is_mmcboot
    rm -f "$dest/partitions.conf"
    while IFS=", " read partnumber partloc start_location partsize partfile partattrs partsha; do
        # Need to trim off leading blanks
        devnum=$(echo "$partloc" | cut -d':' -f 1)
        instnum=$(echo "$partloc" | cut -d':' -f 2)
        partname=$(echo "$partloc" | cut -d':' -f 3)
        # SPI is 3:0
        # eMMC boot blocks (boot0/boot1) are 0:3
        # eMMC user is 1:3
        # NVMe (any external device) is 9:0
        if [ $devnum -eq 3 -a $instnum -eq 0 ] || [ $devnum -eq 0 -a $instnum -eq 3 ]; then
            if [ -n "$partfile" ]; then
                cp "$partfile" "$dest/"
            fi
            if [ $devnum -eq 3 -a $instnum -eq 0 ]; then
                is_spi=yes
            elif [ $devnum -eq 0 -a $instnum -eq 3 ]; then
                is_mmcboot=yes
            fi
            echo "$partname:$start_location:$partsize:$partfile" >> "$dest/partitions.conf"
        fi
    done < flash.idx
    if [ -n "$is_spi" ]; then
        if [ -n "$is_mmcboot" ]; then
            echo "ERR: found bootloader entries for both SPI flash and eMMC boot partitions" >&2
            return 1
        fi
        echo "spi" > "$dest/boot_device_type"
    elif [ -n "$is_mmcboot" ]; then
        echo "mmcboot" > "$dest/boot_device_type"
    else
        echo "ERR: no SPI or eMMC boot partition entries found" >&2
        return 1
    fi
    return 0
}

generate_flash_package_t234() {
    local dev=$(wait_for_usb_storage "$session_id" "flashpkg" "$usb_instance")
    local exports

    if [ -z "$dev" ]; then
        echo "ERR: could not locate USB storage device for sending flashing commands" >&2
        return 1
    fi
    local devsize=$(cat /sys/block/$(basename $dev)/size 2>/dev/null)
    echo "Device size in blocks: $devsize" >&2
    local mnt=$(mount_partition "$dev")
    if [ -z "$mnt" ]; then
        echo "ERR: could not mount USB storage for writing flashing commands" >&2
        return 1
    fi

    mkdir "$mnt/flashpkg/conf"
    rm -f "$mnt/flashpkg/conf/command_sequence"
    touch "$mnt/flashpkg/conf/command_sequence"
    if [ $skip_bootloader -eq 0 ]; then
        echo "bootloader" >> "$mnt/flashpkg/conf/command_sequence"
        mkdir "$mnt/flashpkg/bootloader"
        cp bootloader_staging/* "$mnt/flashpkg/bootloader"
    fi

    echo "extra-pre-wipe" >> "$mnt/flashpkg/conf/command_sequence"

    if [ $erase_nvme -eq 1 ]; then
        echo "erase-nvme" >> "$mnt/flashpkg/conf/command_sequence"
    fi
    if [ $erase_emmc -eq 1 ]; then
        echo "erase-mmc" >> "$mnt/flashpkg/conf/command_sequence"
    else
        [ $EXTERNAL_ROOTFS_DRIVE -eq 0 -o $NO_INTERNAL_STORAGE -eq 1 ] || echo "erase-mmc" >> "$mnt/flashpkg/conf/command_sequence"
    fi

    if [ $erase_only -eq 0 ]; then
        echo "export-devices $ROOTFS_DEVICE" >> "$mnt/flashpkg/conf/command_sequence"
    fi

    echo "extra" >> "$mnt/flashpkg/conf/command_sequence"
    echo "reboot" >> "$mnt/flashpkg/conf/command_sequence"

    # Show what commands were written for debugging
    echo "Commands written to device:" >&2
    cat "$mnt/flashpkg/conf/command_sequence" | while read cmd; do
        echo "  - $cmd" >&2
    done

    # Ensure all data is written before unmounting
    sync

    unmount_and_release "$mnt" "$dev" || return 1
}

write_to_device_t234() {
    local devname="$1"
    local flashlayout="$2"
    local opts="$3"
    local rewritefiles="internal-secureflash.xml"
    local datased simgname rc=1
    local extraarg
    local dev

    # For external devices like nvme0n1, wait for exported storage with size validation
    if echo "$devname" | grep -qE '^(nvme[0-9]+n[0-9]+|mmcblk[0-9]+)'; then
        echo "Waiting for exported external storage device: $devname" >&2
        dev=$(wait_for_exported_storage "$session_id" "$devname" "$usb_instance" 1000)
    else
        # For other devices (like flashpkg), use regular waiting
        dev=$(wait_for_usb_storage "$session_id" "$devname" "$usb_instance")
    fi

    if [ -z "$dev" ]; then
        echo "ERR: could not find $devname" >&2
        return 1
    fi
    if [ -e external-secureflash.xml ]; then
        rewritefiles="external-secureflash.xml,$rewritefiles"
    fi
    "$here/nvflashxmlparse" --rewrite-contents-from=$rewritefiles -o initrd-flash.xml "$flashlayout"
    if [ -n "$DATAFILE" ]; then
        datased="-es,DATAFILE,$DATAFILE,"
    else
        datased="-e/DATAFILE/d"
    fi
    # For the pre-signed case, the flash layout will contain the
    # name of the sparseimage file, and we need to convert it back to
    # the raw image name.
    simgname="${ROOTFS_IMAGE%.*}.img"
    sed -i -e"s,$simgname,$ROOTFS_IMAGE," -e"s,APPFILE_b,$ROOTFS_IMAGE," -e"s,APPFILE,$ROOTFS_IMAGE," -e"s,DTB_FILE,kernel_$DTBFILE," $datased initrd-flash.xml
    if "$here/make-sdcard" -y $opts $extraarg initrd-flash.xml "$dev"; then
        rc=0
    fi
    if ! unmount_and_release "" "$dev"; then
        rc=1
    fi
    return $rc
}

get_final_status_t234() {
    local dtstamp="$1"
    local dev=$(wait_for_usb_storage "$session_id" "flashpkg" "$usb_instance")
    local mnt final_status logdir logfile
    if [ -z "$dev" ]; then
        echo "ERR: could not get final status from device" >&2
        return 1
    fi
    mnt=$(mount_partition "$dev")
    if [ -z "$mnt" ]; then
        echo "ERR: could not mount USB device to get final status from device" >&2
        return 1
    fi
    final_status=$(cat $mnt/flashpkg/status)
    if [ -d "$mnt/flashpkg/logs" ]; then
        logdir="device-logs-$dtstamp"
        if [ -d "$logdir" ]; then
            echo "Logs directory $logdir already exists, replacing" >&2
            rm -rf "$logdir"
        fi
        mkdir "$logdir"
        for logfile in "$mnt"/flashpkg/logs/*; do
            [ -f "$logfile" ] || continue
            cp "$logfile" "$logdir/"
        done
    fi
    unmount_and_release "$mnt" "$dev" || return 1
    echo "Final status: $final_status"
    return 0
}

# ===========================================================================
# T264 (Thor) functions - unified flash flow
# ===========================================================================

get_board_info_t264() {
    if ! "$here/$FLASH_HELPER" $instance_args --get-board-info 2>&1 >>"$logfile"; then
        echo "ERR: could not retrieve board information" >&2
        exit 1
    fi
    . ./boardvars.sh
    if echo "$CHIP_SKU" | grep -q ":" 2>/dev/null; then
        chip_sku=$(echo "$CHIP_SKU" | cut -d: -f4)
    else
        chip_sku=$CHIP_SKU
    fi
    echo "Board ID($BOARDID) version($FAB) sku($BOARDSKU) revision($BOARDREV) Chip SKU($chip_sku) ramcode($RAMCODE)"
}

prepare_binaries_t264() {
    local target="$1"
    local layout_xml="$2"
    local kernel="$3"
    local rootfs_img="$4"
    local datafile="$5"

    if [ "$target" = "internal" ]; then
        if [ -z "$PRESIGNED" ]; then
            if ! MACHINE=$MACHINE BOARDID=$BOARDID FAB=$FAB BOARDSKU=$BOARDSKU BOARDREV=$BOARDREV CHIPREV=$CHIPREV CHIP_SKU=$CHIP_SKU serial_number=$serial_number \
                 "$here/$FLASH_HELPER" --no-flash --sign -u "$keyfile" -v "$sbk_keyfile" --datafile "$datafile" $instance_args "$layout_xml" "$kernel" "$rootfs_img"; then
                return 1
            fi
            cp secureflash.xml internal-secureflash.xml
            mv flash.idx internal-flash.idx
        fi
        mkdir -p tools/kernel_flash/images/internal
        if ! stage_files_for_uniflash tools/kernel_flash/images/internal internal-flash.idx internal-secureflash.xml; then
            return 1
        fi
        return 0
    elif [ "$target" = "external" ]; then
        if [ -z "$PRESIGNED" ]; then
            if ! MACHINE=$MACHINE BOARDID=$BOARDID FAB=$FAB BOARDSKU=$BOARDSKU BOARDREV=$BOARDREV CHIPREV=$CHIPREV CHIP_SKU=$CHIP_SKU \
                 "$here/$FLASH_HELPER" --no-flash --sign --external-device -u "$keyfile" -v "$sbk_keyfile" --datafile "$datafile" $instance_args "$layout_xml" "$kernel" "$rootfs_img"; then
                return 1
            fi
            mv secureflash.xml external-secureflash.xml
            mv flash.idx external-flash.idx
        fi
        mkdir -p tools/kernel_flash/images/external
        if ! stage_files_for_uniflash tools/kernel_flash/images/external external-flash.idx external-secureflash.xml; then
            return 1
        fi
        return 0
    elif [ "$target" = "rcm-boot" ]; then
        if [ -z "$PRESIGNED" ]; then
            rm -rf rcmboot_blob
            if ! MACHINE=$MACHINE BOARDID=$BOARDID FAB=$FAB BOARDSKU=$BOARDSKU BOARDREV=$BOARDREV CHIPREV=$CHIPREV CHIP_SKU=$CHIP_SKU serial_number=$serial_number \
                 "$here/$FLASH_HELPER" --no-flash --rcm-boot -u "$keyfile" -v "$sbk_keyfile" --datafile "$datafile" $instance_args "$layout_xml" "$kernel" "$rootfs_img"; then
                echo "ERR: could not create RCM boot blob" >&2
                return 1
            fi
        fi
        rm -rf bootloader
        mkdir bootloader
        cp -R applet bootloader/
        cp -R rcmboot_blob bootloader/
        echo "$RAMCODE" > bootloader/ramcode.txt
        return 0
    else
        echo "ERR: internal error, unrecognized target: $target" >&2
        return 1
    fi
}

update_flash_cfg_for_partition() {
    local flash_idx_partname="$1"
    local storageline="$2"
    local dest="$3"
    local blksize partnumber partname start_location partsize partfile partguid parttype fstype partfilltoend
    eval "$storageline"
    if [ "$partname" = "$flash_idx_partname" -a -n "$partfile" ]; then
        cp "$partfile" "$dest/"
        echo "${partname}_ext=$partfile" >> "$dest/flash.cfg"
        echo "INFO: staged $dest/$partfile for partition $partname"
    fi
}

stage_files_for_uniflash() {
    local dest="$1"
    local flash_idx="$2"
    local layout_xml="$3"
    local partnumber partloc partname start_location partsize partfile partattrs partsha
    local which=$(basename "$dest")
    local devnum instnum
    local -a partitions
    if [ -n "$layout_xml" ]; then
        mapfile partitions < <("./nvflashxmlparse" -t rootfs "$layout_xml")
    fi
    while IFS=", " read partnumber partloc start_location partsize partfile partattrs partsha; do
        devnum=$(echo "$partloc" | cut -d':' -f 1)
        instnum=$(echo "$partloc" | cut -d':' -f 2)
        partname=$(echo "$partloc" | cut -d':' -f 3)
        if [ -n "$partfile" ]; then
            cp "$partfile" "$dest/" || return 1
        else
            for pline in "${partitions[@]}"; do
                update_flash_cfg_for_partition "$partname" "$pline" "$dest"
            done
        fi
    done < "$flash_idx"
    cp "$flash_idx" "$dest/flash.idx" || return 1
    if [ "$which" = "internal" -a -e flash-upi.idx ]; then
        while IFS=", " read partnumber partloc start_location partsize partfile partattrs partsha; do
            if [ -n "$partfile" ]; then
                cp "$partfile" "$dest/" || return 1
            fi
        done < flash-upi.idx
        cp flash-upi.idx "$dest/" || return 1
    fi
    return 0
}

# ===========================================================================
# Main flow
# ===========================================================================

dtstamp=$(date +"%Y-%m-%d-%H.%M.%S")
logfile="log.initrd-flash.$dtstamp"
stepnumber=1

step_banner() {
    local msg="$1"
    echo "== Step $stepnumber: $msg at $(date -Is) ==" | tee -a "$logfile"
    stepnumber=$(expr $stepnumber \+ 1)
}

echo "Starting at $(date -Is)" | tee "$logfile"
echo "Machine:       ${MACHINE}" | tee "$logfile"
echo "Rootfs device: ${BOOTDEV}" | tee "$logfile"
if ! wait_for_rcm 2>&1 | tee -a "$logfile"; then
    echo "ERR: Device not found at $(date -Is)" | tee -a "$logfile"
    exit 1
fi
if [ -z "$usb_instance" -a -e ".found-jetson" ]; then
    . .found-jetson
fi
if [ -n "$usb_instance" ]; then
    instance_args="--usb-instance $usb_instance"
fi

# Branch based on chip ID
if [ "$CHIPID" = "0x23" ]; then
    # ===================================================================
    # T234 (Orin) flow - tegraflash.py with USB mass storage
    # ===================================================================
    step_banner "Signing binaries"
    rm -rf bootloader_staging
    mkdir bootloader_staging
    if ! sign_binaries_t234 2>&1 >>"$logfile"; then
        echo "ERR: signing failed at $(date -Is)" | tee -a "$logfile"
        exit 1
    fi
    if [ -z "$PRESIGNED" ]; then
        [ ! -f ./boardvars.sh ] || . ./boardvars.sh
    fi

    step_banner "Boot Jetson via RCM"
    if ! wait_for_rcm 2>&1 | tee -a "$logfile"; then
        echo "ERR: Device not found at $(date -Is)" | tee -a "$logfile"
        exit 1
    fi
    if ! run_rcm_boot_t234 2>&1 >>"$logfile"; then
        echo "ERR: RCM boot failed at $(date -Is)" | tee -a "$logfile"
        exit 1
    fi
    [ ! -f ./boardvars.sh ] || . ./boardvars.sh

    if [ -z "$serial_number" ]; then
        echo "WARN: did not get device serial number at $(date -Is)" | tee -a "$logfile"
        session_id=
    else
        session_id=$(printf "%x" "$serial_number" | tail -c8)
    fi

    step_banner "Sending flash sequence commands"
    if ! generate_flash_package_t234 2>&1 | tee -a "$logfile"; then
        echo "ERR: could not create command package at $(date -Is)" | tee -a "$logfile"
        exit 1
    fi

    if [ $erase_only -eq 1 ]; then
        step_banner "Erase-only mode -- skipping partition writing"
    elif [ $EXTERNAL_ROOTFS_DRIVE -eq 1 ]; then
        step_banner "Writing partitions on external storage device"
        if ! write_to_device_t234 $ROOTFS_DEVICE external-flash.xml.in 2>&1 | tee -a "$logfile"; then
            echo "ERR: write failure to external storage at $(date -Is)" | tee -a "$logfile"
            if [ $early_final_status -eq 0 ]; then
                exit 1
            fi
        fi
    else
        step_banner "Writing partitions on internal storage device"
        if ! write_to_device_t234 $ROOTFS_DEVICE flash.xml.in 2>&1 | tee -a "$logfile"; then
            echo "ERR: write failure to internal storage at $(date -Is)" | tee -a "$logfile"
            if [ $early_final_status -eq 0 ]; then
                exit 1
            fi
        fi
    fi

    if [ $erase_only -eq 1 ]; then
        # In erase-only mode the device erases and reboots -- it doesn't re-export
        # the flashpkg device for status, so skip waiting for final status.
        echo "Erase-only mode complete -- device will reboot after erasing" | tee -a "$logfile"
        echo "Successfully finished at $(date -Is)" | tee -a "$logfile"
    else
        step_banner "Waiting for final status from device"
        if ! get_final_status_t234 "$dtstamp" 2>&1 | tee -a "$logfile"; then
            echo "ERR: failed to retrieve device status at $(date -Is)" | tee -a "$logfile"
            echo "Host-side log:              $logfile"
            echo "Device-side logs stored in: device-logs-$dtstamp"
            exit 1
        fi
        echo "Successfully finished at $(date -Is)" | tee -a "$logfile"
    fi
    echo "Host-side log:              $logfile"
    echo "Device-side logs stored in: device-logs-$dtstamp"

elif [ "$CHIPID" = "0x26" ]; then
    # ===================================================================
    # T264 (Thor) flow - unified flash
    # ===================================================================
    get_board_info_t264

    rm -rf tools/kernel_flash/images

    if [ $skip_bootloader -eq 0 ] ; then
        step_banner "Preparing contents for QSPI boot flash"
        if ! prepare_binaries_t264 internal flash.xml.in $LNXFILE $ROOTFS_IMAGE $DATAFILE 2>&1 >>"$logfile"; then
            echo "ERR: preparing QSPI partitions failed at $(date -Is)"  | tee -a "$logfile"
            exit 1
        fi
    fi

    if [ $qspi_only -eq 0 ] && [ -e external-flash.xml.in ]; then
        step_banner "Preparing contents for external storage"
        if ! prepare_binaries_t264 external external-flash.xml.in $LNXFILE $ROOTFS_IMAGE $DATAFILE 2>&1 >>"$logfile"; then
            echo "ERR: preparing external partitions failed at $(date -Is)"  | tee -a "$logfile"
            exit 1
        fi
    fi

    step_banner "Preparing for RCM boot"
    if ! prepare_binaries_t264 rcm-boot rcmboot-flash.xml.in initrd-flash.img $ROOTFS_IMAGE $DATAFILE 2>&1 >>"$logfile"; then
        echo "ERR: preparing RCM boot blob at $(date -Is)"  | tee -a "$logfile"
        exit 1
    fi

    step_banner "Setting up unified flash workspace"
    export CHIP_SKU
    convargs="--profile base"
    if [ $qspi_only -eq 0 -a $EXTERNAL_ROOTFS_DRIVE -eq 1 ]; then
        convargs="$convargs --external-device $ROOTFS_DEVICE external-secureflash.xml"
    fi
    if [ -n "$BOOTSEC_MODE" ]; then
        convargs="$convargs --security-mode $BOOTSEC_MODE"
    fi
    rm -rf out
    mkdir out
    ./unified_flash/tools/flashtools/bootburn/create_bsp_images.py -b jetson-t264 --toolsonly -l -g $PWD/out --l4t
    mkdir -p out/flash_workspace/flash-images out/flash_workspace/rcm-boot
    ./create_l4t_bsp_images.py $convargs --info --dest $PWD/out
    ./create_l4t_bsp_images.py $convargs --dest $PWD/out/flash_workspace/flash-images
    if [ -n "$partition_name" ]; then
        ./create_l4t_bsp_images.py $convargs -k $partition_name --dest $PWD/out/flash_workspace/flash-images
    fi
    ./create_l4t_bsp_images.py $convargs --dest $PWD/out/flash_workspace/rcm-boot --rcm-boot
    cp -R out/flash_workspace/rcm-boot out/flash_workspace/rcm-flash
    cat > out/doflash.sh <<EOF
here=\$(readlink -f \$(dirname "\$0"))
oldwd="\$PWD"
"\$here/tools/flashtools/bootburn/flash_bsp_images.py" -b jetson-t264 --l4t -P "\$here/flash_workspace" $instance_args "\$@"
rc=\$?
cd "\$oldwd"
exit \$rc
EOF
    chmod +x out/doflash.sh

    step_banner "Running unified flash"
    ./out/doflash.sh $uniflash_flags 2>&1 | tee -a "$logfile"
    uniflash_rc="${PIPESTATUS[0]}"

    # Trigger device exit from the flashing initramfs.
    #
    # The legacy T23x initrd-flash device-side init reboots when the host
    # deauthorizes the USB endpoint. NVIDIA's T264 unified-flash flow
    # (flash_bsp_images.py -> FlashImages) does not include any reboot step
    # at the end — the device is left running adbd in the flashing initramfs
    # until something tells it to reboot. Send `adb reboot` so the freshly
    # flashed system boots without requiring a manual reset.
    if [ "${uniflash_rc:-0}" -eq 0 ]; then
        adb_bin=""
        if [ -x "./unified_flash/tools/flashtools/flash/adb" ]; then
            adb_bin="./unified_flash/tools/flashtools/flash/adb"
        elif command -v adb >/dev/null 2>&1; then
            adb_bin="$(command -v adb)"
        fi
        if [ -n "$adb_bin" ]; then
            echo "Issuing 'adb reboot' to leave flashing initramfs..." | tee -a "$logfile"
            # adb reboot returns non-zero because the device disconnects
            # mid-call; the reboot has already been initiated by then.
            "$adb_bin" reboot 2>&1 | tee -a "$logfile" || true
        else
            echo "WARN: adb binary not found; device may need manual reset" | tee -a "$logfile"
        fi
    fi

    echo "Finished at $(date -Is)" | tee -a "$logfile"
    echo "Host-side log:              $logfile"

else
    echo "ERR: unsupported CHIPID: $CHIPID" >&2
    exit 1
fi

# ===========================================================================
# Final USB disconnect (chip-independent)
# ===========================================================================
# Goal: confirm the device has detached. After a clean flash the device
# leaves recovery on its own, so finding the path already gone is the
# success case — not a warning. Only escalate to WARN if a *known-attached*
# device fails to deauthorize.
if [ -n "$usb_instance" ] || [ -n "$session_id" ]; then
    echo "Verifying USB device detachment at end of script..." | tee -a "$logfile"

    # Re-resolve the current USB instance via session_id since the path can
    # change (or vanish) after the device reboots out of recovery.
    final_usb_instance="$usb_instance"
    if [ -n "$session_id" ]; then
        rescanned_dev=$(find_device_by_session "$session_id")
        if [ -n "$rescanned_dev" ]; then
            rescanned_instance=$(find_usb_instance_from_device "$rescanned_dev")
            if [ -n "$rescanned_instance" ]; then
                echo "Device still present at $rescanned_dev with USB instance $rescanned_instance" | tee -a "$logfile"
                final_usb_instance="$rescanned_instance"
            fi
        fi
    fi

    # Settle window: wait up to 5s for the device to detach on its own.
    # On a successful T264 unified flash this typically takes <1s, but USB
    # enumeration races with our script exit on slower hubs.
    settle_path=""
    [ -n "$final_usb_instance" ] && settle_path="/sys/bus/usb/devices/$final_usb_instance"
    if [ -n "$settle_path" ] && [ -e "$settle_path" ]; then
        for _ in 1 2 3 4 5 6 7 8 9 10; do
            [ -e "$settle_path" ] || break
            sleep 0.5
        done
    fi

    if [ -z "$final_usb_instance" ] || [ ! -e "$settle_path" ]; then
        echo "Device already detached — flash completed cleanly" | tee -a "$logfile"
    else
        # Route through the shared helper so the agent path applies here
        # too when running inside the avocado-vm. The helper handles the
        # AVOCADO_AGENT_SOCK / sysfs fallback dispatch.
        echo "Forcing deauthorize on lingering device $final_usb_instance" | tee -a "$logfile"
        disconnect_usb_device "$final_usb_instance" "$session_id" || \
            echo "WARN: failed to deauthorize $final_usb_instance" | tee -a "$logfile"
    fi
fi

exit 0
