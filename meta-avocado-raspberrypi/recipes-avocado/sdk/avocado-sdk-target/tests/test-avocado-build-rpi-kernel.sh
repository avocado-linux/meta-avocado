#!/bin/bash
# Exercises the pinned-kernel staging in avocado-build-rpi against a fake prefix.
set -u
here=$(cd "$(dirname "$0")" && pwd)
snip=$(sed -n "/^# Kernel: the lockfile-pinned kernel/,/^echo .*Kernel from the project's pin/p" "$here/../avocado-build-rpi")
P=$(mktemp -d); trap 'rm -rf "$P"' EXIT
input_dir=$P/rt; mkdir -p $input_dir $P/kernel/6.6
echo default > $input_dir/Image; echo pinned66 > $P/kernel/6.6/Image
dst=$input_dir/rekeyed/Image; fail=0
run() { ( unset AVOCADO_KERNEL_IMAGE; export "$@" 2>/dev/null; eval "$snip" ) >/dev/null 2>&1; }
check() { [ "$2" = "$3" ] && echo "ok   $1" || { echo "FAIL $1: got '$2' want '$3'"; fail=1; }; }
run AVOCADO_KERNEL_IMAGE=$P/kernel/6.6/Image; check "pinned kernel staged" "$(cat $dst 2>/dev/null)" pinned66
run X=1; check "unset fails closed" "$?" 1
check "unset leaves no stale override" "$(cat $dst 2>/dev/null || echo none)" none
run AVOCADO_KERNEL_IMAGE=$P/kernel/6.12/Image; check "missing pin fails closed" "$?" 1
check "bootfiles Image untouched" "$(cat $input_dir/Image)" default
exit $fail
