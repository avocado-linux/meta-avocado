#!/usr/bin/env bash
#
# Regression test for the NVMe flash target knob in
# stone-provision-tegraflash.sh (CARRIER_NVME_PCI / AVOCADO_PROVISION_NVME_PCI).
#
# The nvme branch flashes nvme0n1, which is whichever controller's PCIe link
# came up first in the flashing kernel. On a carrier with two NVMe slots the
# same provision landed on either disk (observed on a Jetson AGX Thor carrier,
# C3 x2 and C5 x4 slots: one run flashed nvme0n1 on C3, the next on C5) and left
# the other disk's old OS behind to win a later boot. A carrier now pins the
# slot by PCIe address; the branch hands it to initrd-flash as ROOTFS_NVME_PCI.
#
# Runs the branch's own code against throwaway files.

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

echo "test-nvme-flash-target: $TARGET"

nvme_branch=$(awk '/^[[:space:]]*nvme\)/{f=1; next} f&&/^[[:space:]]*;;/{exit} f{print}' "$TARGET")
if [ -z "$nvme_branch" ]; then
  fail "could not locate the nvme) branch of the boot-media case"
  echo "test-nvme-flash-target: FAIL (1)"
  exit 1
fi

# run_branch <carrier.env content or empty> <env override or empty>
run_branch() {
  local carrier="$1" override="$2" tmp
  tmp=$(mktemp -d)
  printf 'BOOTDEV="placeholder"\nROOTFS_DEVICE="placeholder"\nEXTERNAL_ROOTFS_DRIVE=0\n' \
    >"$tmp/.env.initrd-flash"
  [ -n "$carrier" ] && printf '%s\n' "$carrier" >"$tmp/carrier.env"
  (
    # shellcheck disable=SC2034  # read by the branch lifted from the script
    build_dir="$tmp"
    if [ -n "$override" ]; then
      # shellcheck disable=SC2034
      AVOCADO_PROVISION_NVME_PCI="$override"
    else
      unset AVOCADO_PROVISION_NVME_PCI
    fi
    eval "$nvme_branch"
  ) >"$tmp/out" 2>&1
  branch_rc=$?
  branch_env=$(cat "$tmp/.env.initrd-flash")
  rm -rf "$tmp"
}

# --- 1. nothing declared: nvme0n1 as before, no pin -------------------------
run_branch "" ""
if [ "$branch_rc" -eq 0 ] && grep -q 'ROOTFS_DEVICE="nvme0n1"' <<<"$branch_env" \
  && ! grep -q 'ROOTFS_NVME_PCI' <<<"$branch_env"; then
  pass "no knob: nvme0n1 and no ROOTFS_NVME_PCI (single-NVMe boards unchanged)"
else
  fail "no knob: rc=$branch_rc env=$(tr '\n' ' ' <<<"$branch_env")"
fi

# --- 2. the carrier's slot reaches initrd-flash ------------------------------
run_branch 'CARRIER_NVME_PCI="0005:01:00.0"' ""
if [ "$branch_rc" -eq 0 ] && grep -qx 'ROOTFS_NVME_PCI="0005:01:00.0"' <<<"$branch_env"; then
  pass "CARRIER_NVME_PCI becomes ROOTFS_NVME_PCI"
else
  fail "carrier knob not written: rc=$branch_rc env=$(tr '\n' ' ' <<<"$branch_env")"
fi

run_branch "CARRIER_NVME_PCI='0003:01:00.0'" ""
if grep -qx 'ROOTFS_NVME_PCI="0003:01:00.0"' <<<"$branch_env"; then
  pass "a single-quoted carrier value is read too"
else
  fail "single-quoted value not read: env=$(tr '\n' ' ' <<<"$branch_env")"
fi

# --- 3. the operator override wins ------------------------------------------
run_branch 'CARRIER_NVME_PCI="0005:01:00.0"' "0003:01:00.0"
if grep -qx 'ROOTFS_NVME_PCI="0003:01:00.0"' <<<"$branch_env" \
  && [ "$(grep -c 'ROOTFS_NVME_PCI' <<<"$branch_env")" -eq 1 ]; then
  pass "AVOCADO_PROVISION_NVME_PCI overrides carrier.env (one line written)"
else
  fail "override not applied: env=$(tr '\n' ' ' <<<"$branch_env")"
fi

# --- 4. malformed values are refused before they reach .env.initrd-flash -----
for bad in "5:1:0.0" "0005:01:00" "/sys/bus/pci/devices/0005:01:00.0" "0005:01:00.0;reboot" "nvme1n1"; do
  run_branch "" "$bad"
  if [ "$branch_rc" -ne 0 ] && ! grep -q 'ROOTFS_NVME_PCI' <<<"$branch_env"; then
    pass "'$bad' is refused"
  else
    fail "'$bad' was accepted: rc=$branch_rc env=$(tr '\n' ' ' <<<"$branch_env")"
  fi
done

echo
if [ "$failures" -eq 0 ]; then
  echo "test-nvme-flash-target: PASS"
  exit 0
fi
echo "test-nvme-flash-target: FAIL ($failures)"
exit 1
