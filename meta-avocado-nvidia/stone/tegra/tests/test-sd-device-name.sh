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
# Neither name is a safe default - mmcblk1 misses the card on an eMMC-less
# module, mmcblk0 IS the eMMC on a module that has one - so the board declares
# it (manifest `storage_devices.rootdisk.tegraflash.sd_device`), an operator can
# override it for one run (AVOCADO_PROVISION_SD_DEVICE), and providing neither
# is an error. That is what the cases below assert: no re-hardcode can pass the
# "nothing declared" case, since it would write a device name instead of
# failing.
#
# Note for a future reader tempted to "correct" the Orin Nano value back: the
# BSP's own generic/cfg/flash_t234_qspi_sd*.xml files do say mmcblk1p1. Those
# are written for eMMC-bearing modules. A config file cannot settle what a
# given board enumerates; only the board can.

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

# Run the branch's own code against a throwaway .env.initrd-flash, rather than
# asserting on source text: this proves the substitution lands, and proves the
# rejected inputs leave the file alone. Each case gets a fresh fixture.
# Results come back in branch_rc / branch_out / branch_env.
run_branch() {
  local manifest_dev="$1" env_dev="$2" tmp
  tmp=$(mktemp -d)
  printf 'BOOTDEV="placeholder"\nROOTFS_DEVICE="placeholder"\nEXTERNAL_ROOTFS_DRIVE=0\n' \
    >"$tmp/.env.initrd-flash"
  (
    # shellcheck disable=SC2034  # all read by the branch lifted from the script
    build_dir="$tmp"
    # shellcheck disable=SC2034
    AVOCADO_STONE_MANIFEST="$tmp/stone-manifest.json"
    # shellcheck disable=SC2034
    tegraflash_sd_device="$manifest_dev"
    if [ -n "$env_dev" ]; then
      # shellcheck disable=SC2034
      AVOCADO_PROVISION_SD_DEVICE="$env_dev"
    else
      unset AVOCADO_PROVISION_SD_DEVICE
    fi
    eval "$sd_branch"
  ) >"$tmp/out" 2>&1
  branch_rc=$?
  branch_out=$(cat "$tmp/out")
  branch_env=$(cat "$tmp/.env.initrd-flash")
  rm -rf "$tmp"
}

# --- 1. the board's declared device is what gets written ---------------------
# Both values are exercised: an eMMC-less module (mmcblk0, the case observed on
# hardware) and an eMMC-bearing one (mmcblk1, what the BSP xml assumes). A
# branch that hardcoded either would fail one of them.
run_branch "mmcblk0" ""
if grep -q 'ROOTFS_DEVICE="mmcblk0"' <<<"$branch_env" &&
  grep -q 'BOOTDEV="mmcblk0p1"' <<<"$branch_env"; then
  pass "a declared mmcblk0 reaches BOOTDEV and ROOTFS_DEVICE"
else
  fail "mmcblk0 not written; got: $(grep -E '^(BOOTDEV|ROOTFS_DEVICE)=' <<<"$branch_env" | tr '\n' ' ')"
fi

if grep -q 'EXTERNAL_ROOTFS_DRIVE=1' <<<"$branch_env"; then
  pass "EXTERNAL_ROOTFS_DRIVE is set for SD boot"
else
  fail "EXTERNAL_ROOTFS_DRIVE was not set; the target would look for an internal rootfs"
fi

run_branch "mmcblk1" ""
if grep -q 'ROOTFS_DEVICE="mmcblk1"' <<<"$branch_env" &&
  grep -q 'BOOTDEV="mmcblk1p1"' <<<"$branch_env"; then
  pass "a declared mmcblk1 reaches BOOTDEV and ROOTFS_DEVICE"
else
  fail "mmcblk1 not written; got: $(grep -E '^(BOOTDEV|ROOTFS_DEVICE)=' <<<"$branch_env" | tr '\n' ' ')"
fi

# --- 2. the environment override wins over the manifest ----------------------
# The probe value is deliberately one no board would declare, so this cannot
# pass by coincidence the way mmcblk0 or mmcblk1 could.
run_branch "mmcblk0" "mmcblk3"
if grep -q 'ROOTFS_DEVICE="mmcblk3"' <<<"$branch_env" &&
  grep -q 'BOOTDEV="mmcblk3p1"' <<<"$branch_env"; then
  pass "AVOCADO_PROVISION_SD_DEVICE overrides the manifest value"
else
  fail "override ignored; got: $(grep -E '^(BOOTDEV|ROOTFS_DEVICE)=' <<<"$branch_env" | tr '\n' ' ')"
fi

# --- 3. with nothing declared the branch must refuse, not guess --------------
# This is also the guard against a reintroduced hardcode: any default would
# write a device name here instead of failing.
run_branch "" ""
if [ "$branch_rc" -ne 0 ] && grep -q 'placeholder' <<<"$branch_env"; then
  pass "no declared device: the branch fails and writes nothing"
else
  fail "no declared device: rc=$branch_rc, env=$(tr '\n' ' ' <<<"$branch_env")"
fi

if grep -q 'sd_device' <<<"$branch_out" && grep -q 'AVOCADO_PROVISION_SD_DEVICE' <<<"$branch_out"; then
  pass "the refusal names both places the device can be declared"
else
  fail "refusal does not name the manifest key and the env var: $(head -3 <<<"$branch_out")"
fi

# --- 4. a malformed override is rejected before it reaches sed ---------------
# /dev/mmcblk1 is the natural mistake - every other device reference an
# operator sees is a /dev path - and unvalidated it makes sed die with "unknown
# option to `s'". A value containing & would substitute the matched text.
for bad in "/dev/mmcblk1" "mmcblk0p1" "mmcblk0&"; do
  run_branch "mmcblk0" "$bad"
  if [ "$branch_rc" -ne 0 ] && grep -q 'placeholder' <<<"$branch_env"; then
    pass "override '$bad' is rejected and .env.initrd-flash is left alone"
  else
    fail "override '$bad' was not rejected: rc=$branch_rc, env=$(tr '\n' ' ' <<<"$branch_env")"
  fi
done

echo
if [ "$failures" -eq 0 ]; then
  echo "test-sd-device-name: PASS"
  exit 0
fi
echo "test-sd-device-name: FAIL ($failures)"
exit 1
