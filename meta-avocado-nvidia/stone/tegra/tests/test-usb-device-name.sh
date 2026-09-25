#!/usr/bin/env bash
#
# Regression test for the USB boot-media device name in
# stone-provision-tegraflash.sh.
#
# The usb branch names the block device the target should export, exactly as
# the sd branch does, but it resolves that name from ONE place rather than two
# and that asymmetry is the thing most likely to be "corrected" later.
#
# sd_device is declared per board because which mmcblkN the card lands on is a
# property of the module: an eMMC-less module puts it at mmcblk0, one carrying
# eMMC at mmcblk1. A USB disk has no equivalent. SCSI letters are handed out in
# attach order, so the same stick is sda on its own and sdb behind a card
# reader that claimed sda first. Observed 2026-09-18 on the bench Jetson Orin
# Nano Developer Kit: the stick enumerated at sda with an empty reader slot at
# sdb, and a second reader would have swapped them.
#
# So there is no board file that could hold the answer, and a value committed
# to a manifest would become a standing default that destroys whatever holds
# that letter on every later flash. The blast radius is what makes the
# asymmetry worth it: a wrong mmcblkN can only reach storage soldered to the
# module, while a wrong sdX is somebody's unrelated USB disk.
#
# Case 4 below is the guard for that: a manifest-shaped value must NOT be
# consulted. A future change that adds a `usb_device` manifest lookup for
# symmetry with sd will fail it.
#
# The partition suffix is the other usb-specific contract. The kernel rule is
# that a device name ending in a digit takes a `p` separator (nvme0n1p1,
# mmcblk0p1) and one ending in a letter does not (sda1). Case 1 pins `sda1`,
# so a copy-paste from the sd branch carrying `p1` fails.

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

echo "test-usb-device-name: $TARGET"

# Isolate the usb branch of the boot-media case: the `usb)` label through its
# terminating `;;`. Anchored after leading whitespace so the profile-name case's
# `tegraflash-usb)` label cannot match.
usb_branch=$(awk '/^[[:space:]]*usb\)/{f=1; next} f&&/^[[:space:]]*;;/{exit} f{print}' "$TARGET")

if [ -z "$usb_branch" ]; then
  fail "could not locate the usb) branch of the boot-media case"
  echo "test-usb-device-name: FAIL (1)"
  exit 1
fi

# Run the branch's own code against a throwaway .env.initrd-flash rather than
# asserting on source text: this proves the substitution lands, and proves a
# rejected input leaves the file alone. Each case gets a fresh fixture.
# `manifest_dev` seeds a tegraflash_usb_device variable the branch must ignore.
run_branch() {
  local manifest_dev="$1" env_dev="$2" tmp
  tmp=$(mktemp -d)
  printf 'BOOTDEV="placeholder"\nROOTFS_DEVICE="placeholder"\nEXTERNAL_ROOTFS_DRIVE=0\n' \
    >"$tmp/.env.initrd-flash"
  (
    # shellcheck disable=SC2034  # read by the branch lifted from the script
    build_dir="$tmp"
    # shellcheck disable=SC2034
    tegraflash_usb_device="$manifest_dev"
    if [ -n "$env_dev" ]; then
      # shellcheck disable=SC2034
      AVOCADO_PROVISION_USB_DEVICE="$env_dev"
    else
      unset AVOCADO_PROVISION_USB_DEVICE
    fi
    eval "$usb_branch"
  ) >"$tmp/out" 2>&1
  branch_rc=$?
  branch_out=$(cat "$tmp/out")
  branch_env=$(cat "$tmp/.env.initrd-flash")
  rm -rf "$tmp"
}

# --- 1. the operator's device reaches the env file, with no `p` separator ----
run_branch "" "sda"
if grep -q 'ROOTFS_DEVICE="sda"' <<<"$branch_env" &&
  grep -q 'BOOTDEV="sda1"' <<<"$branch_env"; then
  pass "sda reaches BOOTDEV as sda1 and ROOTFS_DEVICE as sda"
else
  fail "sda not written; got: $(grep -E '^(BOOTDEV|ROOTFS_DEVICE)=' <<<"$branch_env" | tr '\n' ' ')"
fi

if ! grep -q 'BOOTDEV="sdap1"' <<<"$branch_env"; then
  pass "no mmc-style p separator on a letter-terminated device name"
else
  fail "BOOTDEV carries a p separator; sda1 is the correct form"
fi

if grep -q 'EXTERNAL_ROOTFS_DRIVE=1' <<<"$branch_env"; then
  pass "EXTERNAL_ROOTFS_DRIVE is set for USB boot"
else
  fail "EXTERNAL_ROOTFS_DRIVE was not set; the target would look for an internal rootfs"
fi

# A second letter, so case 1 cannot pass by a hardcoded sda.
run_branch "" "sdb"
if grep -q 'ROOTFS_DEVICE="sdb"' <<<"$branch_env" &&
  grep -q 'BOOTDEV="sdb1"' <<<"$branch_env"; then
  pass "a different letter is honoured (sdb, not a hardcoded sda)"
else
  fail "sdb not written; got: $(grep -E '^(BOOTDEV|ROOTFS_DEVICE)=' <<<"$branch_env" | tr '\n' ' ')"
fi

# --- 2. with nothing declared the branch must refuse, not guess --------------
run_branch "" ""
if [ "$branch_rc" -ne 0 ] && grep -q 'placeholder' <<<"$branch_env"; then
  pass "no declared device: the branch fails and writes nothing"
else
  fail "no declared device: rc=$branch_rc, env=$(tr '\n' ' ' <<<"$branch_env")"
fi

if grep -q 'AVOCADO_PROVISION_USB_DEVICE' <<<"$branch_out"; then
  pass "the refusal names the env var that declares the device"
else
  fail "refusal does not name AVOCADO_PROVISION_USB_DEVICE: $(head -3 <<<"$branch_out")"
fi

# --- 3. a malformed value is rejected before it reaches sed ------------------
# /dev/sda is the natural mistake - every other device reference an operator
# sees is a /dev path - and unvalidated it makes sed die with "unknown option
# to `s'". A value containing & would substitute the matched text instead. A
# partition suffix is rejected because the whole disk is what gets written.
for bad in "/dev/sda" "sda1" "sda&" "nvme0n1" "mmcblk0" "sd"; do
  run_branch "" "$bad"
  if [ "$branch_rc" -ne 0 ] && grep -q 'placeholder' <<<"$branch_env"; then
    pass "value '$bad' is rejected and .env.initrd-flash is left alone"
  else
    fail "value '$bad' was not rejected: rc=$branch_rc, env=$(tr '\n' ' ' <<<"$branch_env")"
  fi
done

# --- 4. there is no manifest fallback, and adding one must fail this ---------
# A manifest-declared value is exactly the standing default the header explains
# this branch must not have. If a future change reintroduces the lookup for
# symmetry with sd, this case writes sdz and fails.
run_branch "sdz" ""
if [ "$branch_rc" -ne 0 ] && grep -q 'placeholder' <<<"$branch_env"; then
  pass "a manifest-shaped usb_device is ignored; the branch still refuses"
else
  fail "a manifest value was consulted: rc=$branch_rc, env=$(tr '\n' ' ' <<<"$branch_env")"
fi

# The env var still wins when both are present, so the ignore above is not
# simply the branch being broken.
run_branch "sdz" "sda"
if grep -q 'ROOTFS_DEVICE="sda"' <<<"$branch_env"; then
  pass "the operator's value is used when a manifest-shaped value is also set"
else
  fail "env value not used; got: $(grep -E '^ROOTFS_DEVICE=' <<<"$branch_env")"
fi

echo
if [ "$failures" -eq 0 ]; then
  echo "test-usb-device-name: PASS"
  exit 0
fi
echo "test-usb-device-name: FAIL ($failures)"
exit 1
