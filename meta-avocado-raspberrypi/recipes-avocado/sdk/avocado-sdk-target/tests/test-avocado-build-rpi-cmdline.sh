#!/bin/bash
# Exercises the cmdline composition in avocado-build-rpi against a fake prefix.
set -u
here=$(cd "$(dirname "$0")" && pwd)
snip=$(sed -n "/^# Kernel command line from the project/,/^fi$/p" "$here/../avocado-build-rpi")
P=$(mktemp -d); trap 'rm -rf "$P"' EXIT
input_dir=$P/rt; mkdir -p $input_dir/bootfiles
printf 'console=serial0,115200 root=/dev/mmcblk0p2 rootwait\n' > $input_dir/bootfiles/cmdline.txt
fail=0; dst=$input_dir/rekeyed/bootfiles/cmdline.txt
run() { ( unset AVOCADO_KERNEL_CMDLINE AVOCADO_KERNEL_CMDLINE_EXTRA; export "$@" 2>/dev/null; eval "$snip" ) >/dev/null 2>&1; }
want() { got=$(cat $dst 2>/dev/null || echo "<none>"); [ "$got" = "$2" ] && echo "ok   $1" || { echo "FAIL $1: got '$got' want '$2'"; fail=1; }; }
run AVOCADO_KERNEL_CMDLINE_EXTRA="avocado.board_tests=1"; want "extra appends" "console=serial0,115200 root=/dev/mmcblk0p2 rootwait avocado.board_tests=1"
run AVOCADO_KERNEL_CMDLINE_EXTRA="avocado.board_tests=1"; want "idempotent" "console=serial0,115200 root=/dev/mmcblk0p2 rootwait avocado.board_tests=1"
run AVOCADO_KERNEL_CMDLINE="root=/dev/sda2 quiet"; want "cmdline replaces" "root=/dev/sda2 quiet"
run X=1; want "neither set removes the override" "<none>"
[ "$(cat $input_dir/bootfiles/cmdline.txt)" = "console=serial0,115200 root=/dev/mmcblk0p2 rootwait" ] && echo "ok   BSP copy untouched" || { echo "FAIL BSP copy changed"; fail=1; }
exit $fail
