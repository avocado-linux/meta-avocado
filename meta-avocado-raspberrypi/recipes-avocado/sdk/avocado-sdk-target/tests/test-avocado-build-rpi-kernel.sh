#!/bin/bash
# Exercises the pinned-kernel staging (Image, device trees) in avocado-build-rpi
# against a fake prefix.
set -u
here=$(cd "$(dirname "$0")" && pwd)
snip=$(sed -n "/^# Kernel: the lockfile-pinned kernel/,/^echo .*Device trees from the project's pin/p" "$here/../avocado-build-rpi")
P=$(mktemp -d); trap 'rm -rf "$P"' EXIT
AVOCADO_PREFIX=$P; input_dir=$P/rt; mkdir -p $input_dir $P/kernel/6.6 $P/rootfs/boot
echo default > $input_dir/Image; echo default > $input_dir/bcm2712-rpi-5-b.dtb
echo pinned66 > $P/kernel/6.6/Image
echo dtb66 > $P/rootfs/boot/bcm2712-rpi-5-b.dtb; echo ovl66 > $P/rootfs/boot/dwc2.dtbo
dst=$input_dir/rekeyed; fail=0
run() { ( unset AVOCADO_KERNEL_IMAGE; export "$@" 2>/dev/null; eval "$snip" ) >/dev/null 2>&1; }
check() { [ "$2" = "$3" ] && echo "ok   $1" || { echo "FAIL $1: got '$2' want '$3'"; fail=1; }; }
run AVOCADO_KERNEL_IMAGE=$P/kernel/6.6/Image; rc=$?
check "pin staged: exit 0" "$rc" 0
check "pinned kernel staged" "$(cat $dst/Image 2>/dev/null)" pinned66
check "pinned device tree staged" "$(cat $dst/bcm2712-rpi-5-b.dtb 2>/dev/null)" dtb66
check "pinned overlay staged" "$(cat $dst/dwc2.dtbo 2>/dev/null)" ovl66
run X=1; check "unset fails closed" "$?" 1
check "unset leaves no stale kernel" "$(cat $dst/Image 2>/dev/null || echo none)" none
run AVOCADO_KERNEL_IMAGE=$P/kernel/6.12/Image; check "missing pin fails closed" "$?" 1
rm $P/rootfs/boot/*; run AVOCADO_KERNEL_IMAGE=$P/kernel/6.6/Image; check "no device trees fails closed" "$?" 1
check "no stale device tree left" "$(cat $dst/bcm2712-rpi-5-b.dtb 2>/dev/null || echo none)" none
check "bootfiles copies untouched" "$(cat $input_dir/Image $input_dir/bcm2712-rpi-5-b.dtb | tr '\n' ' ')" "default default "
exit $fail
