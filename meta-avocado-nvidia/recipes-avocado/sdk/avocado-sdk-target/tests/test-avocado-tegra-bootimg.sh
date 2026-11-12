#!/usr/bin/env bash
# Host test with a fake boot.img header and a fake mkbootimg: the command line
# is read from the base header, AVOCADO_KERNEL_CMDLINE replaces it,
# AVOCADO_KERNEL_CMDLINE_EXTRA appends to it, and an empty or over-long line
# fails before anything is written.

# ok and bad only echo and increment, so `cond && ok || bad` cannot run both.
# shellcheck disable=SC2015
set -u
here=$(cd "$(dirname "$0")" && pwd)
script=$here/../avocado-tegra-bootimg
w=$(mktemp -d)
trap 'rm -rf "$w"' EXIT
pass=0
fail=0
ok() {
  echo "  ok   - $1"
  pass=$((pass + 1))
}
bad() {
  echo "  FAIL - $1"
  fail=$((fail + 1))
}

# Android boot_img_hdr v0: 64 bytes of fields, then a 512-byte cmdline.
hdr() { {
  printf 'ANDROID!'
  head -c 56 /dev/zero
  printf '%s' "$1"
  head -c $((512 - ${#1})) /dev/zero
} >"$2"; }
hdr "console=ttyTCU0,115200 root=PARTLABEL=APP" "$w/base.img"
: >"$w/Image"
: >"$w/initrd"
# Fake mkbootimg: records the --cmdline it was given in the output file.
# The $# and $1-style expansions belong to the generated script, not this one.
# shellcheck disable=SC2016
printf '#!/bin/sh\nwhile [ $# -gt 0 ]; do case $1 in --cmdline) c=$2;; --output) o=$2;; esac; shift; done\nprintf %%s "$c" > "$o"\n' >"$w/mkbootimg"
chmod +x "$w/mkbootimg"
run() {
  rm -f "$w/out.img"
  env -u AVOCADO_KERNEL_CMDLINE -u AVOCADO_KERNEL_CMDLINE_EXTRA "$@" sh "$script" "$w/mkbootimg" "$w/base.img" "$w/Image" "$w/initrd" "$w/out.img" 2>&1
}

msg=$(run)
rc=$?
{ [ $rc -eq 0 ] && [ "$(cat "$w/out.img")" = "console=ttyTCU0,115200 root=PARTLABEL=APP" ]; } && ok "the base header's cmdline is carried over" || bad "carry: rc=$rc $msg"

msg=$(run AVOCADO_KERNEL_CMDLINE_EXTRA="systemd.zram=0 nvme.use_threaded_interrupts=0")
rc=$?
{ [ $rc -eq 0 ] && [ "$(cat "$w/out.img")" = "console=ttyTCU0,115200 root=PARTLABEL=APP systemd.zram=0 nvme.use_threaded_interrupts=0" ]; } && ok "cmdline_extra is appended" || bad "extra: rc=$rc $msg"

msg=$(run AVOCADO_KERNEL_CMDLINE="console=ttyTCU0,115200 quiet")
rc=$?
{ [ $rc -eq 0 ] && [ "$(cat "$w/out.img")" = "console=ttyTCU0,115200 quiet" ]; } && ok "cmdline replaces the line" || bad "replace: rc=$rc $msg"

long=$(printf 'x%.0s' $(seq 1 480))
msg=$(run AVOCADO_KERNEL_CMDLINE_EXTRA="$long")
rc=$?
{ [ $rc -ne 0 ] && [ ! -e "$w/out.img" ] && echo "$msg" | grep -q "holds 511"; } && ok "a line over 511 bytes fails before packing" || bad "length: rc=$rc $msg"

hdr "" "$w/base.img"
msg=$(run)
rc=$?
{ [ $rc -ne 0 ] && [ ! -e "$w/out.img" ]; } && ok "an empty base cmdline fails closed" || bad "empty: rc=$rc $msg"
msg=$(run AVOCADO_KERNEL_CMDLINE="console=ttyTCU0,115200")
rc=$?
{ [ $rc -eq 0 ] && [ "$(cat "$w/out.img")" = "console=ttyTCU0,115200" ]; } && ok "an explicit cmdline still packs over an empty base" || bad "replace-empty: rc=$rc $msg"
msg=$(run AVOCADO_KERNEL_CMDLINE_EXTRA="quiet")
rc=$?
{ [ $rc -ne 0 ] && [ ! -e "$w/out.img" ]; } && ok "cmdline_extra alone does not stand in for an empty base" || bad "extra-on-empty: rc=$rc $(cat "$w/out.img" 2>/dev/null)"

# Only a v0-v2 header has its cmdline at offset 64: another magic or a v3+
# header is not read, so with no kernel.cmdline there is no base line.
hdr "console=ttyTCU0,115200 root=PARTLABEL=APP" "$w/base.img"
printf 'ANDROIX!' | dd of="$w/base.img" conv=notrunc status=none
msg=$(run)
rc=$?
{ [ $rc -ne 0 ] && [ ! -e "$w/out.img" ] && echo "$msg" | grep -q "magic='ANDROIX!'"; } && ok "a header without the Android magic is not read" || bad "magic: rc=$rc $msg"
hdr "console=ttyTCU0,115200 root=PARTLABEL=APP" "$w/base.img"
printf '\003' | dd of="$w/base.img" bs=1 seek=40 conv=notrunc status=none
msg=$(run)
rc=$?
{ [ $rc -ne 0 ] && [ ! -e "$w/out.img" ] && echo "$msg" | grep -q "header_version='3'"; } && ok "a v3 header is not read at the v0-v2 offset" || bad "v3: rc=$rc $msg"

echo "$pass passed, $fail failed"
[ $fail -eq 0 ]
