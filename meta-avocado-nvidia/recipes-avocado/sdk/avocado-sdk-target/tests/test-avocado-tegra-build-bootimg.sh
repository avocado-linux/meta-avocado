#!/usr/bin/env bash
# Host test with a fake SDK prefix: the build-time boot.img uses the kernel the
# rootfs sysroot pins, never another kernel left in kernel/ by an earlier pin,
# and an ambiguous or missing pin fails instead of picking one.
set -u
here=$(cd "$(dirname "$0")" && pwd); script=$here/../avocado-tegra-build-bootimg
w=$(mktemp -d); trap 'rm -rf "$w"' EXIT
pass=0; fail=0; ok(){ echo "  ok   - $1"; pass=$((pass+1)); }; bad(){ echo "  FAIL - $1"; fail=$((fail+1)); }
P=$w/prefix; in=$w/in
mkdir -p "$P/rootfs/boot" "$P/kernel/6.8.12-l4t" "$P/kernel/6.18.35-yocto" "$in/tegraflash-tools" "$w/bin"
: > "$P/kernel/6.8.12-l4t/Image"; : > "$P/kernel/6.18.35-yocto/Image"; : > "$in/initrd"
printf '#!/bin/sh\n' > "$in/tegraflash-tools/mkbootimg"; chmod +x "$in/tegraflash-tools/mkbootimg"
# Fake packer: records the kernel it was handed.
printf '#!/bin/sh\necho "$3" > "$5"\n' > "$w/bin/avocado-tegra-bootimg"; chmod +x "$w/bin/avocado-tegra-bootimg"
run(){ rm -f "$in/boot.img"; AVOCADO_PREFIX=$P PATH="$w/bin:$PATH" sh "$script" "$in" initrd boot.img 2>&1; }

: > "$P/rootfs/boot/Image-6.18.35-yocto"
msg=$(run); rc=$?
{ [ $rc -eq 0 ] && [ "$(cat "$in/boot.img")" = "$P/kernel/6.18.35-yocto/Image" ]; } && ok "the rootfs pin selects its kernel sysroot over a stale one" || bad "pin: rc=$rc $msg"

rm -rf "$P/kernel/6.18.35-yocto"
msg=$(run); rc=$?
{ [ $rc -eq 0 ] && [ "$(cat "$in/boot.img")" = "$P/rootfs/boot/Image-6.18.35-yocto" ]; } && ok "falls back to the rootfs copy when the kernel sysroot is absent" || bad "fallback: rc=$rc $msg"

: > "$P/rootfs/boot/Image-6.8.12-l4t"
msg=$(run); rc=$?
{ [ $rc -ne 0 ] && [ ! -e "$in/boot.img" ]; } && ok "two kernels in the rootfs fail instead of picking one" || bad "ambiguous: rc=$rc $msg"

rm -f "$P/rootfs/boot/"Image-*
msg=$(run); rc=$?
{ [ $rc -ne 0 ] && [ ! -e "$in/boot.img" ]; } && ok "no pinned kernel fails" || bad "none: rc=$rc $msg"

echo "$pass passed, $fail failed"; [ $fail -eq 0 ]
