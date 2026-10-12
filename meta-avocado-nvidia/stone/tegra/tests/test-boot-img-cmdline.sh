#!/usr/bin/env bash
#
# The machine's KERNEL_ARGS are carried into the repacked boot.img only from a
# header they can be read from safely, and never at the cost of the rootfs
# PARTUUIDs.
#
# stone-provision-tegraflash.sh reads the prebuilt boot.img's command line at
# the Android v0-v2 offset (64, 512 bytes). On any other header that offset
# holds part of another field, which is non-empty and looks plausible, so the
# read is gated on the "ANDROID!" magic and header_version <= 2. The combined
# command line is then refused past 511 bytes, because mkbootimg silently moves
# the overflow into extra_cmdline and the PARTUUID arguments are the tail that
# would move.
#
# This lifts the real read-and-guard block out of the script and runs it
# against fake boot.img headers built here.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROVISION="$SCRIPT_DIR/../stone-provision-tegraflash.sh"
failures=0

pass() { printf '  ok   %s\n' "$1"; }
fail() {
  printf '  FAIL %s\n' "$1"
  failures=$((failures + 1))
}

[ -f "$PROVISION" ] || {
  echo "not found: $PROVISION" >&2
  exit 1
}

echo "test-boot-img-cmdline: $PROVISION"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# The block runs at top level inside the kernel-repack branch, so lift it out
# rather than running a flash: from the cmdline reset to the end of the length
# guard. The anchors are the variable names, not the magic or the limit, so a
# change to either reaches the assertions below instead of the extraction.
awk '/^  prebuilt_cmdline=""$/{f=1} f{print} f&&/\$\{#boot_cmdline\}/{g=1} g&&/^  fi$/{exit}' \
  "$PROVISION" >"$work/cmdline.sh"
if ! grep -q 'boot\.img' "$work/cmdline.sh" || ! grep -q '{#boot_cmdline}' "$work/cmdline.sh"; then
  fail "could not extract the boot.img cmdline block"
  echo "test-boot-img-cmdline: FAIL (1)"
  exit 1
fi

A=11111111-2222-4333-8444-555555555555
B=AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE
BASE="avocado.root_partuuid=$A avocado.root_partuuid_b=$B"
SHORT="console=ttyTCU0,115200 pcie_aspm=off nvme_core.default_ps_max_latency_us=0"

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

# run_block <boot.img> -> rc; the resulting boot_cmdline lands in
# $work/cmdline.result and the block's own output in $work/block.out.
run_block() {
  rm -f "$work/cmdline.result"
  (
    build_dir="$work/build"
    mkdir -p "$build_dir"
    cp "$1" "$build_dir/boot.img"
    boot_cmdline="$BASE"
    # shellcheck disable=SC1091
    . "$work/cmdline.sh"
    printf '%s' "$boot_cmdline" >"$work/cmdline.result"
  ) >"$work/block.out" 2>&1
}

result() { cat "$work/cmdline.result" 2>/dev/null; }

# Positive control: a valid v2 header with a short cmdline is read back
# exactly, ahead of the PARTUUIDs. Without it, the rejections below could pass
# because nothing is ever read.
make_bootimg "$work/v2.img" 'ANDROID!' 2 "$SHORT"
if run_block "$work/v2.img" && [ "$(result)" = "$SHORT $BASE" ] \
  && ! grep -q WARNING "$work/block.out"; then
  pass "v2 header: KERNEL_ARGS read back exactly, PARTUUIDs appended"
else
  fail "v2 header: got '$(result)': $(head -3 "$work/block.out")"
fi

# Wrong magic: same bytes at offset 64, but not an Android boot header.
make_bootimg "$work/magic.img" 'ANDROIX!' 2 "$SHORT"
if run_block "$work/magic.img" && [ "$(result)" = "$BASE" ] \
  && grep -q "magic='ANDROIX!'" "$work/block.out"; then
  pass "wrong magic: cmdline not read, only the PARTUUIDs, warning names the magic"
else
  fail "wrong magic: got '$(result)': $(head -3 "$work/block.out")"
fi

# Header v3 moved the cmdline; offset 64 is no longer it.
make_bootimg "$work/v3.img" 'ANDROID!' 3 "$SHORT"
if run_block "$work/v3.img" && [ "$(result)" = "$BASE" ] \
  && grep -q "header_version='3'" "$work/block.out"; then
  pass "header v3: cmdline not read, only the PARTUUIDs, warning names the version"
else
  fail "header v3: got '$(result)': $(head -3 "$work/block.out")"
fi

# A full 512-byte cmdline field (no NUL terminator) cannot fit alongside the
# PARTUUIDs, so provisioning must stop rather than let mkbootimg split it.
full=$(head -c 512 /dev/zero | tr '\0' 'x')
make_bootimg "$work/full.img" 'ANDROID!' 2 "$full"
if run_block "$work/full.img"; then
  fail "512-byte cmdline was accepted: '$(result)'"
elif [ ! -e "$work/cmdline.result" ] && grep -q 'over the 511' "$work/block.out"; then
  pass "512-byte cmdline: provisioning stops with the 511-byte error"
else
  fail "512-byte cmdline failed for another reason: $(head -3 "$work/block.out")"
fi

# The limit itself: the combined line at exactly 511 bytes is accepted, at 512
# it is refused. Separator space plus BASE is ${#BASE}+1 bytes.
fit=$((511 - ${#BASE} - 1))
edge=$(head -c "$fit" /dev/zero | tr '\0' 'y')
make_bootimg "$work/edge511.img" 'ANDROID!' 2 "$edge"
if run_block "$work/edge511.img" && [ "$(result)" = "$edge $BASE" ] \
  && [ "$(result | wc -c)" -eq 511 ]; then
  pass "511-byte combined cmdline is accepted"
else
  fail "511-byte combined cmdline: $(head -3 "$work/block.out")"
fi

make_bootimg "$work/edge512.img" 'ANDROID!' 2 "${edge}y"
if run_block "$work/edge512.img"; then
  fail "512-byte combined cmdline was accepted"
elif grep -q 'is 512 bytes, over the 511' "$work/block.out"; then
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
