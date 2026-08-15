#!/usr/bin/env bash
#
# Regression test for the SD boot-media device name in
# stone-provision-tegraflash.sh.
#
# The sd branch of the boot-media case names the block device the target should
# export. It hardcoded mmcblk1, which is only right on a module that also has
# eMMC: eMMC takes mmc0 and the card lands on mmc1. On an eMMC-less module the
# card is the only MMC controller instantiated, so it comes up as mmcblk0 and
# `export-devices mmcblk1` finds nothing.
#
# Observed 2026-08-14 on a Jetson Orin Nano Developer Kit (P3767-0005, no eMMC).
# The target console showed:
#     sdhci-tegra 3400000.mmc: Got CD GPIO
#     mmc0: new ultra high speed SDR104 SDHC card at address 0001
#     mmcblk0: mmc0:0001 USD 29.8 GiB
#     Processing: export-devices mmcblk1
#     Export of mmcblk1 failed
# while the host only ever reported a 120s timeout with no cause, so the real
# error reached the serial console and nowhere else.
#
# Note for a future reader tempted to "correct" this back: the BSP's own
# generic/cfg/flash_t234_qspi_sd*.xml files do say mmcblk1p1. Those are written
# for eMMC-bearing modules. A config file cannot settle what a given board
# enumerates; only the board can.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$SCRIPT_DIR/../stone-provision-tegraflash.sh"
failures=0

pass() { printf '  ok   %s\n' "$1"; }
fail() {
  printf '  FAIL %s\n' "$1"
  failures=$((failures + 1))
}

[ -f "$TARGET" ] || {
  echo "target script not found: $TARGET" >&2
  exit 1
}

echo "test-sd-device-name: $TARGET"

# Isolate the sd branch of the boot-media case: the `sd)` label through its
# terminating `;;`. Asserting over the whole file would also match the emmc and
# nvme branches, which legitimately name mmcblk0 and nvme0n1.
sd_branch=$(awk '/^[[:space:]]*sd\)/{f=1; next} f&&/^[[:space:]]*;;/{exit} f{print}' "$TARGET")

if [ -z "$sd_branch" ]; then
  fail "could not locate the sd) branch of the boot-media case"
  echo "test-sd-device-name: FAIL (1)"
  exit 1
fi

# --- 1. the sd branch must not assume eMMC occupies mmcblk0 ------------------
# Comments are stripped first: the branch documents mmcblk1 as the override
# value for eMMC-bearing modules, and saying so must not trip the check.
sd_code=$(printf '%s\n' "$sd_branch" | grep -v '^[[:space:]]*#')
if printf '%s\n' "$sd_code" | grep -q 'mmcblk1'; then
  fail "sd branch names mmcblk1; an eMMC-less module enumerates the card as mmcblk0"
  printf '%s\n' "$sd_code" | grep -n 'mmcblk1' | sed 's/^/       /'
else
  pass "sd branch does not hardcode mmcblk1"
fi

# --- 2. run the branch's own sed and check what it writes -------------------
# Executing the text lifted out of the script proves the substitution lands,
# rather than only proving the source reads correctly. Each case sets the
# override differently, so the fixture is rebuilt per case.
run_branch() {
  local dev_override="$1" tmp
  tmp=$(mktemp -d)
  printf 'BOOTDEV="placeholder"\nROOTFS_DEVICE="placeholder"\nEXTERNAL_ROOTFS_DRIVE=0\n' \
    >"$tmp/.env.initrd-flash"
  (
    # shellcheck disable=SC2034  # read by the sed lines lifted from the script
    build_dir="$tmp"
    if [ -n "$dev_override" ]; then
      AVOCADO_PROVISION_SD_DEVICE="$dev_override"
      export AVOCADO_PROVISION_SD_DEVICE
    else
      unset AVOCADO_PROVISION_SD_DEVICE
    fi
    eval "$sd_branch"
  )
  cat "$tmp/.env.initrd-flash"
  rm -rf "$tmp"
}

default_out=$(run_branch "")
if grep -q 'ROOTFS_DEVICE="mmcblk0"' <<<"$default_out" &&
  grep -q 'BOOTDEV="mmcblk0p1"' <<<"$default_out"; then
  pass "with no override the branch writes mmcblk0 / mmcblk0p1"
else
  fail "default is not mmcblk0; got: $(grep -E '^(BOOTDEV|ROOTFS_DEVICE)=' <<<"$default_out" | tr '\n' ' ')"
fi

# An eMMC-bearing module still needs mmcblk1, so the name must stay reachable
# without editing the script. The probe value is deliberately one no branch
# would ever hardcode, so this cannot pass by coincidence the way mmcblk1 would.
override_out=$(run_branch "mmcblk3")
if grep -q 'ROOTFS_DEVICE="mmcblk3"' <<<"$override_out" &&
  grep -q 'BOOTDEV="mmcblk3p1"' <<<"$override_out"; then
  pass "AVOCADO_PROVISION_SD_DEVICE overrides both BOOTDEV and ROOTFS_DEVICE"
else
  fail "override ignored; got: $(grep -E '^(BOOTDEV|ROOTFS_DEVICE)=' <<<"$override_out" | tr '\n' ' ')"
fi

# --- 3. the external-rootfs flag must survive either path -------------------
if grep -q 'EXTERNAL_ROOTFS_DRIVE=1' <<<"$default_out"; then
  pass "EXTERNAL_ROOTFS_DRIVE is set for SD boot"
else
  fail "EXTERNAL_ROOTFS_DRIVE was not set; the target would look for an internal rootfs"
fi

echo
if [ "$failures" -eq 0 ]; then
  echo "test-sd-device-name: PASS"
  exit 0
fi
echo "test-sd-device-name: FAIL ($failures)"
exit 1
