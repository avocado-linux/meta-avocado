#!/usr/bin/env bash
# Shared by the rzv2n-sr-som emmc and sd provision profiles (sourced).
#
# U-Boot's `ums 0 mmc <dev>` exposes the board's eMMC (mmc 0) or microSD
# (mmc 1) as a USB disk on the SoC's USB2.0 ch0 (J5003). These helpers find
# that disk by its USB id - never by /dev/sdX name, which another disk on the
# same host (another board's, a card reader) could hold - and write a disk
# image to it.

# The gadget's USB id: CONFIG_USB_GADGET_VENDOR_NUM/PRODUCT_NUM in usb-gadget.cfg.
AVOCADO_RZ_UMS_ID="${AVOCADO_RZ_UMS_ID:-18d1:0d02}"

# Print the /dev node of each whole disk whose USB device is the UMS gadget.
ums_disks() {
  local want_vid=${AVOCADO_RZ_UMS_ID%%:*} want_pid=${AVOCADO_RZ_UMS_ID##*:}
  local blk dir
  for blk in /sys/block/sd*; do
    [ -e "$blk" ] || continue
    dir=$(readlink -f "$blk/device")
    while [ -n "$dir" ] && [ "$dir" != "/" ]; do
      if [ -f "$dir/idVendor" ] && [ -f "$dir/idProduct" ]; then
        if [ "$(cat "$dir/idVendor")" = "$want_vid" ] &&
          [ "$(cat "$dir/idProduct")" = "$want_pid" ]; then
          echo "/dev/$(basename "$blk")"
        fi
        break
      fi
      dir=$(dirname "$dir")
    done
  done
}

# Wait up to $1 seconds for exactly one UMS disk; print it.
wait_ums_disk() {
  local timeout=${1:-60} i disks
  for ((i = 0; i < timeout; i++)); do
    mapfile -t disks < <(ums_disks)
    if [ ${#disks[@]} -eq 1 ] && [ -b "${disks[0]}" ] &&
      [ "$(cat "/sys/block/$(basename "${disks[0]}")/size" 2>/dev/null || echo 0)" -gt 0 ]; then
      echo "${disks[0]}"
      return 0
    fi
    if [ ${#disks[@]} -gt 1 ]; then
      echo "ERROR: more than one USB disk with id $AVOCADO_RZ_UMS_ID: ${disks[*]}" >&2
      return 1
    fi
    sleep 1
  done
  echo "ERROR: no USB disk with id $AVOCADO_RZ_UMS_ID after ${timeout}s." >&2
  echo "In U-Boot on the board: 'ums 0 mmc 0' (eMMC) or 'ums 0 mmc 1' (microSD)," >&2
  echo "with the SoC's USB2.0 ch0 (J5003) connected to this host." >&2
  return 1
}

# write_disk_image <image> <block device>: the whole image, GPT included.
# conv=sparse skips the image's all-zero blocks (the empty B slots and the
# unused space inside the filesystems), leaving whatever the disk held there:
# nothing reads it. oflag=direct + flushbufs: every block is on the device
# before this returns, since the board is power-cycled right after.
write_disk_image() {
  local image=$1 target part img_bytes dev_bytes name
  # Any path to the disk (/dev/disk/by-id/..., a symlink) names its kernel
  # node, which /sys/block and the partition unmounts below go by.
  target=$(readlink -f "$2")
  name=$(basename "$target")
  if [ ! -b "$target" ] || [ ! -e "/sys/block/$name" ]; then
    echo "ERROR: $2 is not a whole disk" >&2
    return 1
  fi
  img_bytes=$(stat -c %s "$image")
  dev_bytes=$(($(cat "/sys/block/$name/size") * 512))
  if [ "$img_bytes" -gt "$dev_bytes" ]; then
    echo "ERROR: $image ($img_bytes bytes) does not fit on $target ($dev_bytes bytes)" >&2
    return 1
  fi
  for part in /sys/block/"$name"/"$name"*; do
    [ -e "$part" ] || continue
    umount "/dev/$(basename "$part")" 2>/dev/null || true
  done
  echo "Writing $(basename "$image") ($((img_bytes / 1048576)) MiB) to $target ($((dev_bytes / 1073741824)) GiB)..."
  dd if="$image" of="$target" bs=1M conv=sparse,fsync oflag=direct status=progress
  sync
  blockdev --flushbufs "$target" 2>/dev/null || true
}
