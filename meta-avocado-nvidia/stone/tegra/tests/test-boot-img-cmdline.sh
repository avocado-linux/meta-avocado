#!/usr/bin/env bash
#
# The machine's KERNEL_ARGS are carried into the repacked boot.img only from a
# header they can be read from safely, and never at the cost of the rootfs
# PARTUUIDs.
#
# stone-provision-tegraflash.sh appends the per-flash rootfs PARTUUIDs through
# AVOCADO_KERNEL_CMDLINE_EXTRA and packs with avocado-tegra-bootimg, the packer
# the build hooks use for the OTA boot.img. The packer reads the prebuilt
# boot.img's command line at the Android v0-v2 offset (64, 512 bytes) only when
# the "ANDROID!" magic and header_version <= 2 say that offset is the cmdline,
# fails closed when no base line is left (a line of PARTUUIDs alone has no
# console=), and refuses past 511 bytes, because mkbootimg silently moves the
# overflow into extra_cmdline and the PARTUUID arguments are the tail that
# would move.
#
# This lifts the real repack block out of the provision script and runs it with
# the real packer and a fake mkbootimg that records the --cmdline it was given.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROVISION="$SCRIPT_DIR/../stone-provision-tegraflash.sh"
PACKER="$SCRIPT_DIR/../../../recipes-avocado/sdk/avocado-sdk-target/avocado-tegra-bootimg"
failures=0

pass() { printf '  ok   %s\n' "$1"; }
fail() {
  printf '  FAIL %s\n' "$1"
  failures=$((failures + 1))
}

for f in "$PROVISION" "$PACKER"; do
  [ -f "$f" ] || {
    echo "not found: $f" >&2
    exit 1
  }
done

echo "test-boot-img-cmdline: $PROVISION"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# From the PARTUUID generation to the packer call: the anchors are the variable
# and the tool name, so a change to either reaches the assertions below
# instead of the extraction. The $ in the patterns is sed's, not the shell's.
# shellcheck disable=SC2016
sed -n '/^  app_partuuid=\$(tr/,/avocado-tegra-bootimg "\$(command -v mkbootimg)"/{p;/avocado-tegra-bootimg "/{n;p}}' \
  "$PROVISION" >"$work/block.sh"
if ! grep -q 'AVOCADO_KERNEL_CMDLINE_EXTRA' "$work/block.sh" || ! grep -q 'avocado-tegra-bootimg' "$work/block.sh"; then
  fail "could not extract the boot.img repack block"
  echo "test-boot-img-cmdline: FAIL (1)"
  exit 1
fi

mkdir -p "$work/bin" "$work/build"
cp "$PACKER" "$work/bin/avocado-tegra-bootimg"
# Fake mkbootimg: records the --cmdline it was given in the output file.
# The $# and $1-style expansions belong to the generated script.
# shellcheck disable=SC2016
printf '#!/bin/sh\nwhile [ $# -gt 0 ]; do case $1 in --cmdline) c=$2;; --output) o=$2;; esac; shift; done\nprintf %%s "$c" > "$o"\n' >"$work/bin/mkbootimg"
chmod +x "$work/bin/avocado-tegra-bootimg" "$work/bin/mkbootimg"
: >"$work/Image"
: >"$work/initrd"

SHORT="console=ttyTCU0,115200 pcie_aspm=off nvme_core.default_ps_max_latency_us=0"
UUID='[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}'
PINS="avocado.root_partuuid=$UUID avocado.root_partuuid_b=$UUID"
SAMPLE=" avocado.root_partuuid=$(head -c 36 /dev/zero | tr '\0' 0) avocado.root_partuuid_b=$(head -c 36 /dev/zero | tr '\0' 0)"
PINS_LEN=${#SAMPLE}

# make_bootimg <file> <8-byte magic> <header_version> <cmdline>
# Android boot header v0-v2: magic at 0, header_version (u32 LE) at 40,
# name[16] at 48, cmdline[512] at 64, id[32] at 576. The fields either side of
# cmdline are filled with non-NUL bytes, as a real image's are, so a read at
# the wrong offset or length picks them up instead of stripping to the same
# string.
make_bootimg() {
  head -c 2048 /dev/zero >"$1"
  printf '%s' "$2" | dd of="$1" bs=1 seek=0 conv=notrunc status=none
  printf '%b' "\\x$(printf '%02x' "$3")\\x00\\x00\\x00" \
    | dd of="$1" bs=1 seek=40 conv=notrunc status=none
  printf '%s' "tegra234-board-n" | dd of="$1" bs=1 seek=48 conv=notrunc status=none
  printf '%s' "$4" | dd of="$1" bs=1 seek=64 conv=notrunc status=none
  head -c 32 /dev/zero | tr '\0' 'I' | dd of="$1" bs=1 seek=576 conv=notrunc status=none
}

# run_block <boot.img> -> rc; the packed cmdline is $work/build/boot.img
# afterwards (the fake mkbootimg writes only the line), the block's output
# goes to $work/block.out.
run_block() {
  cp "$1" "$work/build/boot.img"
  (
    # The block reads these; shellcheck cannot see through the `.`.
    # shellcheck disable=SC2034
    build_dir="$work/build"
    # shellcheck disable=SC2034
    initramfs_in_build="$work/initrd"
    # shellcheck disable=SC2034
    AVOCADO_PROVISION_KERNEL_IMAGE="$work/Image"
    PATH="$work/bin:$PATH"
    unset AVOCADO_KERNEL_CMDLINE AVOCADO_KERNEL_CMDLINE_EXTRA
    # shellcheck disable=SC1091
    . "$work/block.sh"
  ) >"$work/block.out" 2>&1
}

result() { cat "$work/build/boot.img"; }

# Positive control: a valid v2 header with a short cmdline is read back
# exactly, ahead of the PARTUUIDs. Without it, the rejections below could pass
# because nothing is ever read.
make_bootimg "$work/v2.img" 'ANDROID!' 2 "$SHORT"
if run_block "$work/v2.img" && result | grep -Eqx "$SHORT $PINS" \
  && ! grep -q WARNING "$work/block.out"; then
  pass "v2 header: KERNEL_ARGS read back exactly, PARTUUIDs appended"
else
  fail "v2 header: got '$(result)': $(head -3 "$work/block.out")"
fi

# Wrong magic: same bytes at offset 64, but not an Android boot header. With no
# base line left, a line of PARTUUIDs alone has no console=: stop.
make_bootimg "$work/magic.img" 'ANDROIX!' 2 "$SHORT"
if ! run_block "$work/magic.img" && grep -q "magic='ANDROIX!'" "$work/block.out" \
  && grep -q 'no kernel command line' "$work/block.out"; then
  pass "wrong magic: cmdline not read, provisioning stops, warning names the magic"
else
  fail "wrong magic: got '$(result)': $(head -3 "$work/block.out")"
fi

# Header v3 moved the cmdline; offset 64 is no longer it.
make_bootimg "$work/v3.img" 'ANDROID!' 3 "$SHORT"
if ! run_block "$work/v3.img" && grep -q "header_version='3'" "$work/block.out"; then
  pass "header v3: cmdline not read, provisioning stops, warning names the version"
else
  fail "header v3: got '$(result)': $(head -3 "$work/block.out")"
fi

# A full 512-byte cmdline field (no NUL terminator) cannot fit alongside the
# PARTUUIDs, so provisioning must stop rather than let mkbootimg split it.
full=$(head -c 512 /dev/zero | tr '\0' 'x')
make_bootimg "$work/full.img" 'ANDROID!' 2 "$full"
if run_block "$work/full.img"; then
  fail "512-byte cmdline was accepted: '$(result)'"
elif grep -q 'holds 511' "$work/block.out"; then
  pass "512-byte cmdline: provisioning stops with the 511-byte error"
else
  fail "512-byte cmdline failed for another reason: $(head -3 "$work/block.out")"
fi

# The limit itself: the combined line at exactly 511 bytes is accepted, at 512
# it is refused. PINS_LEN is the pins with the space that separates them from
# the base line.
fit=$((511 - PINS_LEN))
edge=$(head -c "$fit" /dev/zero | tr '\0' 'y')
make_bootimg "$work/edge511.img" 'ANDROID!' 2 "$edge"
if run_block "$work/edge511.img" && result | grep -Eqx "$edge $PINS" \
  && [ "$(result | wc -c)" -eq 511 ]; then
  pass "511-byte combined cmdline is accepted"
else
  fail "511-byte combined cmdline: $(head -3 "$work/block.out")"
fi

make_bootimg "$work/edge512.img" 'ANDROID!' 2 "${edge}y"
if run_block "$work/edge512.img"; then
  fail "512-byte combined cmdline was accepted"
elif grep -q 'is 512 bytes; boot.img holds 511' "$work/block.out"; then
  pass "512-byte combined cmdline is refused"
else
  fail "512-byte combined cmdline failed for another reason: $(head -3 "$work/block.out")"
fi

echo
if [ "$failures" -eq 0 ]; then
  echo "test-boot-img-cmdline: PASS"
  exit 0
fi
echo "test-boot-img-cmdline: FAIL ($failures)"
exit 1
