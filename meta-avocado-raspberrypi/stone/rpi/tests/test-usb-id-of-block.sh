#!/bin/bash
# Checks usb_id_of_block from stone-provision-usb.sh against a fake sysfs:
# the unattended write depends on it naming the rpiboot gadget, and only it.
#   bash meta-avocado-raspberrypi/stone/rpi/tests/test-usb-id-of-block.sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
eval "$(sed -n '/^usb_id_of_block() {/,/^}/p' "$here/../stone-provision-usb.sh")"

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
exit $fail
