#!/bin/bash

set -o pipefail

me=$(basename "$0")
here=$(readlink -f $(dirname "$0"))

declare -A DEFAULTS

usage() {
    cat <<EOF
Usage:
  $me [options]

Options:
  -h|--help             Displays this usage information
  --skip-bootloader     Skip boot partition programming
  --usb-instance        USB instance of Jetson device
  --erase-nvme          Erase NVME drive during flashing

Options passed through to flash helper:
  -u                    PKC key file for signing
  -v                    SBK key file for signing

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
early_final_status=0
erase_nvme=0
check_usb_instance="${TEGRAFLASH_CHECK_USB_INSTANCE:-no}"

ARGS=$(getopt -n $(basename "$0") -l "usb-instance:,help,skip-bootloader,erase-nvme" -o "u:v:h" -- "$@")
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
	--skip-bootloader)
	    skip_bootloader=1
	    shift
	    ;;
	--erase-nvme)
	    erase_nvme=1
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
	-h|--help)
	    usage
	    exit 0
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

# Shared function to disconnect USB device by toggling authorized attribute
# This is the reliable method for triggering Jetson devices to detect disconnect
disconnect_usb_device() {
    local usb_instance="$1"
    
    if [ -z "$usb_instance" ]; then
        echo "WARN: No USB instance provided for disconnect" >&2
        return 1
    fi
    
    local authorized_path="/sys/bus/usb/devices/$usb_instance/authorized"
    
    if [ ! -w "$authorized_path" ]; then
        echo "WARN: Cannot write to $authorized_path (device may not exist)" >&2
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
    
    # Set authorized back to 1 (reconnect)
    echo 1 > "$authorized_path" 2>/dev/null || {
        echo "WARN: Failed to reauthorize USB device $usb_instance (this may be expected)" >&2
        return 0  # Still return success as disconnect was achieved
    }
    
    echo "USB device $usb_instance disconnected and reconnected" >&2
    return 0
}

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

# Helper function to get current mounts for a device (container-friendly)
get_device_mounts() {
    local dev="$1"
    # Use mount command output instead of /proc/mounts
    # This works in containers and doesn't require /proc access
    mount | grep "^$dev " | awk '{print $3}' 2>/dev/null || true
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
        local dev_name=$(basename "$dev")
        if command -v blockdev >/dev/null 2>&1; then
            blockdev --flushbufs "$dev" 2>/dev/null || true
        fi
        
        # Use the reliable USB disconnect method via authorized toggle
        if [ -n "$usb_instance" ]; then
            disconnect_usb_device "$usb_instance"
        fi
    fi
    
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
		    # Accept flashpkg devices when waiting for any USB storage device
		    echo "[$candidate] (accepting flashpkg device)" >&2
		    output="$candidate"
		    break
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

copy_bootloader_files() {
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

generate_flash_package() {
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
    [ $EXTERNAL_ROOTFS_DRIVE -eq 0 -o $NO_INTERNAL_STORAGE -eq 1 ] || echo "erase-mmc" >> "$mnt/flashpkg/conf/command_sequence"
    echo "export-devices $ROOTFS_DEVICE" >> "$mnt/flashpkg/conf/command_sequence"

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
    
    # After sending export-devices command, wait for device to reboot and expose the actual storage
    echo "Waiting for device to reboot and export storage device..." >&2
    
    # Show current USB devices for debugging
    if command -v lsusb >/dev/null 2>&1; then
        echo "Current USB devices before disconnect:" >&2
        lsusb | grep -E "(0955|nvidia|flashpkg)" | while read line; do
            echo "  $line" >&2
        done
    fi
    
    # Disconnect USB device to trigger Jetson to process commands
    if [ -n "$usb_instance" ]; then
        echo "Disconnecting USB device to trigger command processing..." >&2
        disconnect_usb_device "$usb_instance"
    fi
    
    # Wait for the command device to disconnect (indicates reboot started)
    echo "Waiting for device to process commands and disconnect..." >&2
    local disconnect_count=0
    local max_disconnect_wait=60  # Increased timeout
    
    while [ $disconnect_count -lt $max_disconnect_wait ]; do
        # Check if block device still exists
        if [ ! -b "$dev" ]; then
            echo "Device $dev disconnected after ${disconnect_count}s" >&2
            break
        fi
        
        # Also check if the USB device is still present in sysfs
        local dev_name=$(basename "$dev")
        if [ ! -e "/sys/block/$dev_name" ]; then
            echo "Device $dev removed from sysfs after ${disconnect_count}s" >&2
            break
        fi
        
        sleep 1
        disconnect_count=$(expr $disconnect_count + 1)
        if [ $(expr $disconnect_count % 5) -eq 0 ]; then
            echo -n "." >&2
        fi
        
        # Show periodic status
        if [ $(expr $disconnect_count % 15) -eq 0 ]; then
            echo -n "[${disconnect_count}s]" >&2
        fi
    done
    
    if [ $disconnect_count -ge $max_disconnect_wait ]; then
        echo "" >&2
        echo "WARNING: Device did not disconnect after ${max_disconnect_wait}s" >&2
        echo "Continuing with device detection..." >&2
    else
        echo "Device disconnected, waiting for reconnection with exported storage..." >&2
    fi
    
    # Give additional time for device to fully reboot and export storage
    sleep 10
}

write_to_device() {
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
    # XXX
    # For the pre-signed case, the flash layout will contain the
    # name of the sparseimage file, and we need to convert it back to
    # the raw image name.
    # XXX
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

get_final_status() {
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
step_banner "Signing binaries"
rm -rf bootloader_staging
mkdir bootloader_staging
if ! sign_binaries 2>&1 >>"$logfile"; then
    echo "ERR: signing failed at $(date -Is)"  | tee -a "$logfile"
    exit 1
fi
if [ -z "$PRESIGNED" ]; then
    [ ! -f ./boardvars.sh ] || . ./boardvars.sh
fi
step_banner "Boot Jetson via RCM"
if ! prepare_for_rcm_boot 2>&1 >>"$logfile"; then
    echo "ERR: Preparing RCM boot command failed at $(date -Is)" | tee -a "$logfile"
    exit 1
fi
if ! wait_for_rcm 2>&1 | tee -a "$logfile"; then
    echo "ERR: Device not found at $(date -Is)" | tee -a "$logfile"
    exit 1
fi
if ! run_rcm_boot 2>&1 >>"$logfile"; then
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

# Boot device flashing
step_banner "Sending flash sequence commands"
if ! generate_flash_package 2>&1 | tee -a "$logfile"; then
    echo "ERR: could not create command package at $(date -Is)" | tee -a "$logfile"
    exit 1
fi
if [ $EXTERNAL_ROOTFS_DRIVE -eq 1 ]; then
    keep_going=1
    step_banner "Writing partitions on external storage device"
    if ! write_to_device $ROOTFS_DEVICE external-flash.xml.in 2>&1 | tee -a "$logfile"; then
	echo "ERR: write failure to external storage at $(date -Is)" | tee -a "$logfile"
	if [ $early_final_status -eq 0 ]; then
	    exit 1
	fi
    fi
else
    step_banner "Writing partitions on internal storage device"
    if ! write_to_device $ROOTFS_DEVICE flash.xml.in 2>&1 | tee -a "$logfile"; then
	echo "ERR: write failure to internal storage at $(date -Is)" | tee -a "$logfile"
	if [ $early_final_status -eq 0 ]; then
	    exit 1
	fi
    fi
fi
step_banner "Waiting for final status from device"
if ! get_final_status "$dtstamp" 2>&1 | tee -a "$logfile"; then
    echo "ERR: failed to retrieve device status at $(date -Is)" | tee -a "$logfile"
    echo "Host-side log:              $logfile"
    echo "Device-side logs stored in: device-logs-$dtstamp"
    exit 1
fi
echo "Successfully finished at $(date -Is)" | tee -a "$logfile"
echo "Host-side log:              $logfile"
echo "Device-side logs stored in: device-logs-$dtstamp"

# Final disconnect of USB device
if [ -n "$usb_instance" ]; then
    echo "Disconnecting USB device at end of script..." | tee -a "$logfile"
    authorized_path="/sys/bus/usb/devices/$usb_instance/authorized"
    if [ -w "$authorized_path" ]; then
        echo 0 > "$authorized_path" 2>/dev/null || true
    fi
fi

exit 0
