#!/bin/bash

set -e

me=$(basename "$0")
here=$(readlink -f $(dirname "$0"))
declare -a PARTS
FINALPART=
DEVNAME=
PARTSEP=
OUTSYSBLK=
HAVEBMAPTOOL=

SUDO=
[ $(id -u) -eq 0 ] || SUDO="sudo"

usage() {
    cat <<EOF

Usage:
  $me [options] [--] <config-file> <output>

Parameters:
  config-file             Name of the flash.xml file with the SDcard partition definitions
  output                  Either the name of an SDcard device, or the name of an SDcard image file to create

Options:
  -h                      Displays this usage information
  -s size                 Sets size of SDcard image when creating an image file (required)
  -b basename             Base filename for SDcard image (required if no output specified)
  -y                      Skip prompting for confirmation
  --honor-start-locations Use the start locations emitted by nvflashxmlparse
  --no-final-part         Skip special handling of final partition
  --serial-number <sn>    Select USB /dev/sd[a-z] device based on serial number
  --keep-connection       Do not disconnect USB drive after use

Confirmation is required if <output> is a device or if it is the name of
a file that already exists.

Size is specified either as number of 512-byte blocks, or can end with
'K', 'M', or 'G' to specify kilo-, mega-, or gigabytes (1000-based rather
than 1024-based). 1% will be subtracted to allow for some overhead on
the card the image will be written to.
EOF
}

compute_size() {
    local s="$1"
    local sfx="${s: -1}"
    if [ "$sfx" = "G" -o "$sfx" = "K" -o "$sfx" = "M" ]; then
	s="${s:0:-1}"
	case "$sfx" in
	    K)
		s=$(expr $s \* 1000)
		;;
	    M)
		s=$(expr $s \* 1000 \* 1000)
		;;
	    G)
		s=$(expr $s \* 1000 \* 1000 \* 1000)
		;;
	esac
	expr \( $s \* 99 / 100 \+ 511 \) / 512
	return 0
    fi
    echo "$s"
    return 0
}

find_finalpart() {
    local blksize partnumber partname start_location partsize partfile partguid parttype fstype partfilltoend
    local appidx app_b_idx pline i
    if [ -n "$ignore_finalpart" ]; then
	FINALPART=999
	return 0
    fi
    i=0
    for pline in "${PARTS[@]}"; do
	eval "$pline"
	if [ $partfilltoend -eq 1 ]; then
	    FINALPART=$i
	    return 0
	fi
	if [ "$partname" = "APP" ]; then
	    appidx=$i
	elif [ "$partname" = "APP_b" ]; then
	    app_b_idx=$i
	fi
	i=$(expr $i + 1)
    done
    if [ -n "$appidx" ]; then
	if [ -n "$app_b_idx" ]; then
	    ignore_finalpart=yes
	    FINALPART=999
	    return 0
	fi
	FINALPART=$appidx
	return 0
    fi
    echo "ERR: no final partition found" >&2
    return 1
}

make_partitions() {
    local blksize partnumber partname start_location partsize partfile partguid parttype fstype partfilltoend
    local i pline alignarg sgdiskcmd parttype
    if [ "$use_start_locations" = "yes" ]; then
	alignarg="-a 1"
    fi
    sgdiskcmd="sgdisk \"$output\" $alignarg"
    i=0
    for pline in "${PARTS[@]}"; do
	if [ $i -ne $FINALPART ]; then
	    eval "$pline"
	    [ -n "$parttype" ] || parttype="0700"
	    if [ "$use_start_locations" != "yes" ]; then
		start_location=0
	    fi
	    printf "  [%02d] name=%s start=%s size=%s sectors\n" $partnumber $partname $start_location $partsize
	    sgdiskcmd="$sgdiskcmd --new=$partnumber:$start_location:+$partsize --typecode=$partnumber:$parttype -c $partnumber:$partname"
	fi
	i=$(expr $i + 1)
    done
    if [ -z "$ignore_finalpart" ]; then
	eval "${PARTS[$FINALPART]}"
	[ -n "$parttype" ] || parttype="8300"
	if [ "$use_start_locations" != "yes" ]; then
	    start_location=0
	fi
	printf "  [%02d] name=%s (fills to end)\n" $partnumber $partname
	sgdiskcmd="$sgdiskcmd --largest-new=$partnumber --typecode=$partnumber:$parttype -c $partnumber:$partname"
    fi
    local errlog=$(mktemp)
    if ! eval "$sgdiskcmd" >/dev/null 2>"$errlog"; then
	echo "ERR: partitioning failed" >&2
	cat "$errlog" >&2
	rm -f "$errlog"
	return 1
    fi
    rm -f "$errlog"
    return 0
}

create_filesystems() {
    local blksize partnumber partname start_location partsize partfile partguid parttype fstype partfilltoend
    local pline mke2fscmd
    local errlog=$(mktemp)
    for pline in "${PARTS[@]}"; do
	eval "$pline"
	if [ -z "$partfile" ] && [ -n "$fstype" ] && [ "$fstype" != "basic" ]; then
	    printf "Creating $fstype filesystem to /dev/$DEVNAME$PARTSEP$partnumber\n"
	    mke2fscmd="mkfs.$fstype /dev/$DEVNAME$PARTSEP$partnumber"
	    if ! eval "$mke2fscmd" >/dev/null 2>"$errlog"; then
		    echo "ERR: filesystem failed" >&2
		    cat "$errlog" >&2
		    rm -f "$errlog"
		    return 1
	    fi
	fi
    done
    rm -f "$errlog"
    return 0
}

copy_to_device() {
    local src="$1"
    local dst="$2"
    if [ -z "$HAVEBMAPTOOL" ]; then
	dd if="$src" of="$dst" conv=fsync status=none >/dev/null 2>&1 || return 1
	return 0
    fi
    local bmap=$(mktemp)
    local rc=0
    bmaptool create -o "$bmap" "$src" >/dev/null 2>&1 || rc=1
    if [ $rc -eq 0 ]; then
	$SUDO bmaptool copy --bmap "$bmap" "$src" "$dst" >/dev/null 2>&1 || rc=1
    fi
    rm "$bmap"
    return $rc
}

unmount_device() {
    local dev="$1"
    # Use mount command instead of /proc/mounts for container compatibility
    # Handle multiple mount points for the same device
    local all_mounts=$(mount | grep "^$dev " | awk '{print $3}')
    local success=0
    
    for mnt in $all_mounts; do
        echo "Unmounting $mnt..."
        if umount "${mnt}" > /dev/null 2>&1; then
            success=1
        else
            # Try force unmount
            echo "Trying force unmount of $mnt..."
            if umount -f "${mnt}" > /dev/null 2>&1; then
                success=1
            else
                # Try lazy unmount as last resort
                echo "Trying lazy unmount of $mnt..."
                umount -l "${mnt}" > /dev/null 2>&1 || true
                success=1
            fi
        fi
        
        # Clean up mount point if it's one we created
        if echo "$mnt" | grep -q "^/tmp/usb_mount"; then
            rmdir "$mnt" 2>/dev/null || true
        fi
    done
    
    return 0
}

write_partitions_to_device() {
    local blksize partnumber partname start_location partsize partfile partguid parttype fstype partfilltoend
    local i dest pline destsize filesize n_written
    n_written=0
    i=0
    for pline in "${PARTS[@]}"; do
	if [ $i -eq $FINALPART ]; then
	    i=$(expr $i + 1)
	    continue
	fi
	eval "$pline"
	if [ -z "$partfile" ]; then
	    i=$(expr $i + 1)
	    continue
	fi
	if [ -e "signed/$partfile" ]; then
	    partfile="signed/$partfile"
	elif [ ! -e "$partfile" ]; then
	    echo "ERR: cannot find file $partfile for partition $partnumber" >&2
	    return 1
	fi
	filesize=$(stat -c "%s" "$partfile")
	dest="/dev/$DEVNAME$PARTSEP$partnumber"
	if [ ! -b "$dest" ]; then
	    echo "ERR: cannot locate block device $dest" >&2
	    return 1
	fi
    if ! unmount_device "$dest"; then
        echo "ERR: device unmount failed" >&2
        return 1
    fi
	destsize=$(blockdev --getsize64 "$dest" 2>/dev/null)
	if [ $n_written -eq 0 -a -z "$destsize" ]; then
	    sleep 1
	    destsize=$(blockdev --getsize64 "$dest" 2>/dev/null)
	fi
	echo "  Writing $partfile (size=$filesize) to $dest (size=$destsize)..."
	if ! copy_to_device "$partfile" "$dest"; then
	    echo "ERR: failed to write $partfile to $dest" >&2
	    return 1
	fi
	n_written=$(expr $n_written + 1)
	i=$(expr $i + 1)
    done
    if [ -n "$ignore_finalpart" ]; then
	return 0
    fi
    eval "${PARTS[$FINALPART]}"
    if [ -n "$partfile" ]; then
	if [ ! -e "$partfile" ]; then
	    echo "ERR: cannot find file $partfile for partition $partnumber" >&2
	    return 1
	fi
	filesize=$(stat -c "%s" "$partfile")
	dest="/dev/$DEVNAME$PARTSEP$partnumber"
    if ! unmount_device "$dest"; then
        echo "ERR: device unmount failed" >&2
        return 1
    fi
	if [ ! -b "$dest" ]; then
	    echo "ERR: cannot locate block device $dest" >&2
	    return 1
	fi
	destsize=$(blockdev --getsize64 "$dest" 2>/dev/null)
	if [ $n_written -eq 0 -a -z "$destsize" ]; then
	    sleep 1
	    destsize=$(blockdev --getsize64 "$dest" 2>/dev/null)
	fi
	echo "  Writing $partfile (size=$filesize) to $dest (size=$destsize)..."
	if ! copy_to_device "$partfile" "$dest"; then
	    echo "ERR: failed to write $partfile to $dest" >&2
	    return 1
	fi
    fi
}

write_partitions_to_image() {
    local -a partstart
    local blksize partnumber partname start_location partsize partfile partguid parttype fstype partfilltoend
    local i s e stuff partstart partend pline

    while read partnumber s e stuff; do
	  partstart[$partnumber]=$s
    done < <(sgdisk "$output" --print | egrep '^ +[0-9]')

    i=0
    for pline in "${PARTS[@]}"; do
	eval "$pline"
	[ -n "$partfile" ] || continue
	if [ -e "signed/$partfile" ]; then
	    partfile="signed/$partfile"
	elif [ ! -e "$partfile" ]; then
	    echo "ERR: cannot find file $partfile for partition $partnumber" >&2
	    return 1
	fi
	echo "  Writing $partfile..."
	if ! dd if="$partfile" of="$output" conv=notrunc seek=${partstart[$partnumber]} status=none >/dev/null 2>&1; then
	    echo "ERR: failed to write $partfile to $output (offset ${partstart[$partnumber]}" >&2
	    return 1
	fi
	i=$(expr $i + 1)
    done
}

confirm() {
    while true; do
	if read -p "About to make an SDcard image on $1. OK? "; then
	    case "${REPLY^^}" in
		Y|YES)
		    return 0
		    ;;
		N|NO)
		    exit 0
		    ;;
		*)
		    echo "Please answer 'yes' or' no'."
		    ;;
	    esac
	else
	    exit 0
	fi
    done
}

ARGS=$(getopt -l "serial-number:,keep-connection,no-final-part,honor-start-locations" -o "yhs:b:" -n "$me" -- "$@")
if [ $? -ne 0 ]; then
    usage
    exit 1
fi

eval set -- "$ARGS"
unset ARGS

preconfirmed=
outsize=
basename=
wait_for_usb_device=
keep_connection=
serial_number=
ignore_finalpart=
use_start_locations=
while true; do
    case "$1" in
	--serial-number)
	    wait_for_usb_device=yes
	    serial_number="$2"
	    shift 2
	    ;;
	--keep-connection)
	    keep_connection=yes
	    shift
	    ;;
	--no-final-part)
	    ignore_finalpart=yes
	    shift
	    ;;
	--honor-start-locations)
	    use_start_locations=yes
	    shift
	    ;;
	-h)
	    usage
	    exit 0
	    ;;
	-y)
	    preconfirmed=yes
	    shift
	    ;;
	-s)
	    outsize=$(compute_size "$2")
	    shift 2
	    ;;
	-b)
	    basename="$2"
	    shift 2
	    ;;
	--)
	    shift
	    break
	    ;;
	*)
	    echo "Error processing arguments" >&2
	    exit 1
	    ;;
    esac
done

if [ ! -e "$here/nvflashxmlparse" ]; then
    echo "ERR: this script requires nvflashxmlparse to exist in the same directory" >&2
    exit 1
fi

cfgfile="$1"
output="$2"

if [ -z "$cfgfile" ]; then
    echo "ERR: missing flash config file parameter" >&2
    exit 1
fi

# Helper function to get device serial from sysfs
get_device_serial() {
    local device="$1"
    local sysfs_path="/sys/block/$(basename "$device")"
    local result=""
    
    # Try to get serial number from device/serial
    if [ -r "$sysfs_path/device/serial" ]; then
        result=$(cat "$sysfs_path/device/serial" 2>/dev/null | tr -d ' \t\n\r')
    fi
    
    echo "$result"
}

# Helper function to find USB device instance (bus-devpath) from a block device
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
            if echo "$usb_path_info" | grep -q '^[0-9]\+-[0-9]\+'; then
                echo "$usb_path_info"
                return 0
            fi
        fi
        current_path=$(dirname "$current_path")
    done
    
    return 1
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

if [ "$wait_for_usb_device" = "yes" ]; then
    echo -n "Looking for USB storage device from $serial_number..."
    output=
    while [ -z "$output" ]; do
	for candidate in /dev/sd[a-z]; do
	    [ -b "$candidate" ] || continue
	    cand_sernum=$(get_device_serial "$candidate")
	    if [ "$cand_sernum" = "$serial_number" ]; then
		echo "[$candidate]"
		output="$candidate"
		break
	    fi
	done
	if [ -z "$output" ]; then
	    sleep 1
	    echo -n "."
	fi
    done
fi

if [ -z "$output" ]; then
    if [ -z "$basename" ]; then
	echo "ERR: missing <output> parameter and no base name specified for SDcard image" >&2
	usage
	exit 1
    fi
    output="${basename}.sdcard"
fi

if [ -c "$output" ]; then
   echo "ERR: $output is a character device" >&2
   exit 1
fi
if [ -b "$output" ]; then
    realoutput=$(readlink -f "$output")
    DEVNAME=$(basename "$realoutput")
    if [ $(dirname "$realoutput") != "/dev" -o ! -e "/sys/block/$DEVNAME" ]; then
	echo "ERR: $output does not appear to be an appropriate device" >&2
	exit 1
    fi
    enddigits=$(echo "$DEVNAME" | sed -r -e's,[a-z]+([0-9]*),\1,')
    [ -z "$enddigits" ] || PARTSEP="p"
    OUTSYSBLK="/sys/block/$DEVNAME"
    outsize=$(cat "$OUTSYSBLK/size")
    [ -n "$preconfirmed" ] || confirm "$output"
else
    if [ -e "$output" ]; then
	[ -n "$preconfirmed" ] || confirm "$output"
	rm "$output"
    fi
    if [ -z "$outsize" ]; then
	echo "ERR: no size specified for SDcard image $output" >&2
	exit 1
    fi
fi

mapfile PARTS < <("$here/nvflashxmlparse" -t rootfs "$cfgfile")
if [ ${#PARTS[@]} -eq 0 ]; then
    echo "No partition definitions found in $cfgfile" >&2
    exit 1
fi

echo  "Creating partitions"
[ -b "$output" ] || dd if=/dev/zero of="$output" bs=512 count=0 seek=$outsize status=none

# Ensure device is not mounted before partitioning
if [ -b "$output" ]; then
    echo "Ensuring device $output is unmounted..."
    unmount_device "$output" || true
    
    # Wait a moment for the device to settle
    sleep 2
    
    # Check if sgdisk is available
    if ! command -v sgdisk >/dev/null 2>&1; then
        echo "ERR: sgdisk command not found - install gdisk package" >&2
        echo "Available partitioning tools:" >&2
        command -v parted >/dev/null 2>&1 && echo "  - parted (available)" >&2 || echo "  - parted (not available)" >&2
        command -v fdisk >/dev/null 2>&1 && echo "  - fdisk (available)" >&2 || echo "  - fdisk (not available)" >&2
        command -v sfdisk >/dev/null 2>&1 && echo "  - sfdisk (available)" >&2 || echo "  - sfdisk (not available)" >&2
        exit 1
    fi
fi

# Try GPT initialization with better error reporting
echo "Initializing GPT on $output..."
if ! sgdisk "$output" --clear --mbrtogpt 2>/tmp/sgdisk_error.log; then
    echo "Initial GPT setup failed, trying --zap-all first..."
    cat /tmp/sgdisk_error.log >&2
    
    if ! sgdisk "$output" --zap-all 2>/tmp/sgdisk_error2.log; then
	echo "ERR: could not initialize GPT on $output" >&2
	echo "sgdisk --zap-all output:" >&2
	cat /tmp/sgdisk_error2.log >&2
	exit 1
    fi
    
    echo "Retrying GPT initialization after zap-all..."
    if ! sgdisk "$output" --clear --mbrtogpt 2>/tmp/sgdisk_error3.log; then
	echo "ERR: could not initialize GPT on $output after --zap-all" >&2
	echo "sgdisk --clear --mbrtogpt output:" >&2
	cat /tmp/sgdisk_error3.log >&2
	exit 1
    fi
fi
echo "GPT initialization successful"

find_finalpart || exit 1
make_partitions || exit 1
if ! sgdisk "$output" --verify >/dev/null 2>&1; then
    echo "ERR: verification failed for $output" >&2
    exit 1
fi
if [ -b "$output" ]; then
    sleep 1
    if ! $SUDO partprobe "$output" >/dev/null 2>&1; then
	echo "ERR: partprobe failed after partitioning $output" >&2
	exit 1
    fi
    sleep 1
    create_filesystems || exit 1
fi
if type -p bmaptool >/dev/null 2>&1; then
    HAVEBMAPTOOL=yes
fi
echo "Writing partitions"
if [ -b "$output" ]; then
    write_partitions_to_device || exit 1
else
    write_partitions_to_image || exit 1
    if ! sgdisk "$output" --verify >/dev/null 2>&1; then
	echo "ERR: verification failed for $output" >&2
	exit 1
    fi
fi
echo "[OK: $output]"
if [ "$wait_for_usb_device" = "yes" -a "$keep_connection" != "yes" ]; then
    echo "Disconnecting $output"
    # Use sync and sysfs-based device management instead of udisksctl
    sync
    
    # Try to flush device buffers using container-friendly methods
    local dev_name=$(basename "$output")
    if command -v blockdev >/dev/null 2>&1; then
        blockdev --flushbufs "$output" 2>/dev/null || true
    fi
    
    # Find USB device instance and disconnect using authorized toggle
    if [ -b "$output" ]; then
        usb_instance=$(find_usb_instance_from_device "$output")
        if [ -n "$usb_instance" ]; then
            disconnect_usb_device "$usb_instance"
        fi
    fi
    
    echo "Device buffers flushed"
fi

# Final disconnect of USB device at end of script
if [ -b "$output" ]; then
    usb_instance=$(find_usb_instance_from_device "$output")
    if [ -n "$usb_instance" ]; then
        authorized_path="/sys/bus/usb/devices/$usb_instance/authorized"
        if [ -w "$authorized_path" ]; then
            echo 0 > "$authorized_path" 2>/dev/null || true
        fi
    fi
fi

exit 0
