#!/usr/bin/env bash
# Host test for the SDK vm helper: finds each target's provisioned image, boots
# qemux86-64 through OVMF on a virtio disk, and pads qemuarm64's sd-card image
# to a power of two without shrinking it. qemu-system-* and qemu-img are stubs
# that record their arguments.
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts, so bad runs only when the check failed
set -u
here=$(cd "$(dirname "$0")" && pwd)
script=${1:-$here/../avocado-sdk-target/vm}
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

# An SDK-shaped tree: the binaries in usr/bin, QEMU's firmware in usr/share/qemu.
bin="$w/sdk/usr/bin"
fw="$w/sdk/usr/share/qemu"
mkdir -p "$bin" "$fw"
for b in qemu-system-x86_64 qemu-system-aarch64 qemu-img; do
  printf '#!/bin/sh\nprintf "%%s\\n" "$@" >>"%s/%s.args"\n' "$w" "$b" >"$bin/$b"
  chmod +x "$bin/$b"
done
echo code >"$fw/edk2-x86_64-code.fd"
echo vars >"$fw/edk2-i386-vars.fd"

# run <target> -> runs the helper for runtime "rt", clearing earlier stub logs.
run() {
  rm -f "$w"/*.args
  PATH="$bin:$PATH" AVOCADO_SDK_TARGET="$1" AVOCADO_PREFIX="$w/prefix" bash "$script" rt </dev/null 2>&1
}
build="$w/prefix/output/runtimes/rt/stone/_build"
mkdir -p "$build"

# 1. qemux86-64 provision names the image after the platform.
x86="$build/avocado-os-avocado-qemux86-64.img"
truncate -s 2500M "$x86"
touch -d '2026-01-01 00:00' "$x86"
out=$(run qemux86-64)
rc=$?
a=$(cat "$w/qemu-system-x86_64.args" 2>/dev/null)
vars="$build/avocado-os-avocado-qemux86-64-efivars.fd"
{ [ $rc -eq 0 ] && grep -qxF "if=pflash,format=raw,readonly=on,file=$bin/../share/qemu/edk2-x86_64-code.fd" <<<"$a" \
  && grep -qxF "if=pflash,format=raw,file=$vars" <<<"$a" && grep -qxF "file=$x86,if=virtio,format=raw" <<<"$a" \
  && ! grep -qx -- '-bios' <<<"$a" && [ "$(cat "$vars")" = vars ]; } \
  && ok "qemux86-64 boots its platform-named image through OVMF on a virtio disk" \
  || bad "x86: rc=$rc out=[$out] args=[$a]"

# 2. The x86 image is never resized: virtio has no power-of-two rule.
{ [ ! -e "$w/qemu-img.args" ] && [ "$(stat -c %s "$x86")" -eq $((2500 * 1048576)) ]; } \
  && ok "qemux86-64's image is left at its size" || bad "x86 resized: [$(cat "$w/qemu-img.args" 2>/dev/null)]"

# 3. The variable store survives a restart, even though the guest has since
#    written to the image, and starts over once deleted.
echo written-by-guest >"$vars"
touch "$x86"
run qemux86-64 >/dev/null
kept=$(cat "$vars")
rm -f "$vars"
run qemux86-64 >/dev/null
{ [ "$kept" = written-by-guest ] && [ "$(cat "$vars")" = vars ]; } \
  && ok "EFI variables persist across runs and start over once deleted" \
  || bad "vars: after restart=[$kept] after delete=[$(cat "$vars" 2>/dev/null)]"

# 4. No OVMF beside the QEMU binary is an error, not a firmware-less boot.
mv "$fw/edk2-x86_64-code.fd" "$w/code.bak"
out=$(run qemux86-64)
rc=$?
mv "$w/code.bak" "$fw/edk2-x86_64-code.fd"
{ [ $rc -ne 0 ] && [ ! -e "$w/qemu-system-x86_64.args" ] && grep -q edk2-x86_64-code.fd <<<"$out"; } \
  && ok "a missing OVMF stops before QEMU starts" || bad "no fw: rc=$rc out=[$out]"

# 5. qemuarm64 keeps u-boot on an sd-card, padded up to a power of two.
arm="$build/avocado-os-qemuarm64.img"
truncate -s 1500M "$arm"
out=$(run qemuarm64)
rc=$?
a=$(cat "$w/qemu-system-aarch64.args" 2>/dev/null)
{ [ $rc -eq 0 ] && [ "$(tr '\n' ' ' <"$w/qemu-img.args")" = "resize -f raw $arm 2048M " ] \
  && grep -qxF -- "-bios" <<<"$a" && grep -qxF "$w/prefix/output/runtimes/rt/stone/flash.bin" <<<"$a" \
  && grep -qxF "sd-card,drive=mmc" <<<"$a"; } \
  && ok "a 1500 MiB qemuarm64 image grows to 2048M, never shrinks to 1024M" \
  || bad "arm: rc=$rc out=[$out] resize=[$(cat "$w/qemu-img.args" 2>/dev/null)] args=[$a]"

# 6. An image already at a power of two is not resized again.
truncate -s 2048M "$arm"
run qemuarm64 >/dev/null
[ ! -e "$w/qemu-img.args" ] && ok "a power-of-two image is not resized" \
  || bad "resized again: [$(cat "$w/qemu-img.args")]"

# 7. No image under either name says so and starts nothing.
rm -f "$x86"
out=$(run qemux86-64)
rc=$?
{ [ $rc -ne 0 ] && [ ! -e "$w/qemu-system-x86_64.args" ] && grep -q "avocado-os-avocado-qemux86-64.img" <<<"$out"; } \
  && ok "a missing image is an error naming both names" || bad "no image: rc=$rc out=[$out]"

echo
echo "passed: $pass  failed: $fail  (checks: $((pass + fail))/7 run)"
[ "$fail" -eq 0 ] && [ $((pass + fail)) -eq 7 ]
