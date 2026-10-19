#!/bin/bash
# Checks usb_id_of_block and gadget_source_of_block from
# stone-provision-usb.sh against a fake sysfs: the unattended write depends on
# them naming the rpiboot gadget and, of its disks, the one this image is for.
#   bash meta-avocado-raspberrypi/stone/rpi/tests/test-usb-id-of-block.sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
eval "$(sed -n '/^usb_id_of_block() {/,/^}/p; /^gadget_source_of_block() {/,/^}/p; /^gadget_disk_is_target() {/,/^}/p' "$here/../stone-provision-usb.sh")"

SYSFS=$(mktemp -d); trap 'rm -rf "$SYSFS"' EXIT
mkdir -p "$SYSFS/block"
# A disk behind a USB device: devices/<usb>/<intf>/host0/target/<lun>
mkdisk() {
    local name=$1 usb=$2 vid=$3 pid=$4
    local lun="$SYSFS/devices/$usb/$usb:1.0/host0/target0:0:0/0:0:0:0"
    mkdir -p "$lun"
    [ -z "$vid" ] || { echo "$vid" > "$SYSFS/devices/$usb/idVendor"; echo "$pid" > "$SYSFS/devices/$usb/idProduct"; }
    mkdir -p "$SYSFS/block/$name"; ln -s "$lun" "$SYSFS/block/$name/device"
}
mkdisk sda 1-1 0a5c 0104   # the rpiboot mass-storage gadget
mkdisk sdb 1-2 0781 5575   # some other USB stick
mkdisk sdc pci0 "" ""      # a disk with no USB ancestor

fail=0
check() { local got; got=$(usb_id_of_block "$1" || echo "none"); [ "$got" = "$2" ] && echo "ok   $1 -> $got" || { echo "FAIL $1 -> $got (want $2)"; fail=1; }; }
check /dev/sda 0a5c:0104
check /dev/sdb 0781:5575
check /dev/sdc none
check /dev/sdz none

# The gadget's disks name their source in the SCSI vendor field (8 chars,
# space padded). A Pi with an NVMe drive exposes both.
mkdisk sdd 2-1 0a5c 0104; printf 'nvme0n1 ' > "$SYSFS/block/sdd/device/vendor"
mkdisk sde 3-1 0a5c 0104; printf 'mmcblk0 ' > "$SYSFS/block/sde/device/vendor"
src() { local got; got=$(gadget_source_of_block "$1" || echo "none"); [ "$got" = "$2" ] && echo "ok   source $1 -> $got" || { echo "FAIL source $1 -> $got (want $2)"; fail=1; }; }
src /dev/sdd nvme0n1
src /dev/sde mmcblk0
src /dev/sda none

# Which new disk to write for an image on the SD card (mmcblk0): the gadget's
# SD disk, not its NVMe; and a gadget that names no Pi block device in the
# vendor field (e.g. "RPi-MSD-") is taken as the single disk it exposes.
mkdisk sdf 4-1 0a5c 0104; printf 'RPi-MSD-' > "$SYSFS/block/sdf/device/vendor"
tgt() { local got=skip; gadget_disk_is_target "$1" mmcblk0 && got=take; [ "$got" = "$2" ] && echo "ok   target $1 -> $got" || { echo "FAIL target $1 -> $got (want $2)"; fail=1; }; }
tgt /dev/sde take
tgt /dev/sdd skip
tgt /dev/sdf take
tgt /dev/sda take
exit $fail
