#!/usr/bin/env bash
#
# get_final_status in initrd-flash.sh must fail when the device reports failure.
#
# The device writes SUCCESS or FAILED to flashpkg/status at the end of a flash.
# The host used to print that value and return 0 regardless, so a device that
# wrote FAILED (observed on a Jetson Orin Nano: QSPI driver rejected, no
# /dev/mtd0, board dark afterwards) still ended in "Successfully finished" and
# `stone provision` reported [SUCCESS].
#
# This runs the real function, lifted out of the script, against a fake
# flashpkg mount for each status the device can leave behind.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$SCRIPT_DIR/../../../recipes-bsp/tegra-binaries/tegra-helper-scripts/initrd-flash.sh"
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

echo "test-final-status: $TARGET"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Sourcing the script whole would run the flash.
awk '/^get_final_status\(\) \{/{f=1} f{print} f&&/^\}$/{exit}' \
  "$TARGET" > "$work/fn.sh"

if [ ! -s "$work/fn.sh" ]; then
  fail "could not extract get_final_status from the script"
  echo "test-final-status: FAIL (1)"
  exit 1
fi

# run_status <status-file-content> -> sets out, rc
run_status() {
  local mnt="$work/mnt"
  rm -rf "$mnt" "$work/run"
  mkdir -p "$mnt/flashpkg" "$work/run"
  printf '%s\n' "$1" > "$mnt/flashpkg/status"
  cat > "$work/harness.sh" <<EOF
set -o pipefail
wait_for_usb_storage() { echo /dev/fake; }
mount_partition() { echo "$mnt"; }
unmount_and_release() { return 0; }
session_id=deadbeef
usb_instance=
EOF
  cat "$work/fn.sh" >> "$work/harness.sh"
  # Called the way the script calls it: through tee, relying on pipefail.
  echo 'get_final_status stamp 2>&1 | tee -a log' >> "$work/harness.sh"
  out="$(cd "$work/run" && bash "$work/harness.sh" 2>&1)"
  rc=$?
}

run_status SUCCESS
# The status line proves the function ran to the end rather than dying early.
if [ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -q "Final status: SUCCESS"; then
  pass "a device that reports SUCCESS succeeds"
else
  fail "SUCCESS did not succeed (rc=$rc): $(printf '%s' "$out" | head -4)"
fi

run_status FAILED
if [ "$rc" -ne 0 ] && printf '%s\n' "$out" | grep -q "Final status: FAILED"; then
  pass "a device that reports FAILED fails, through the tee pipeline"
else
  fail "FAILED did not fail (rc=$rc): $(printf '%s' "$out" | head -4)"
fi

if printf '%s\n' "$out" | grep -q "ERR: device reported final status: FAILED"; then
  pass "the failure names the status the device reported"
else
  fail "no ERR line naming the device status: $(printf '%s' "$out" | head -4)"
fi

# The status the device writes before the host sends commands. Reading it back
# means the flash never completed, which is not success either.
run_status "PENDING: expecting command sequence from host"
if [ "$rc" -ne 0 ]; then
  pass "a device that never finished (PENDING) fails"
else
  fail "PENDING status was treated as success"
fi

# The harness above sets pipefail itself; the call site only sees the
# function's status through `| tee` because the script does too.
if grep -q '^set -o pipefail' "$TARGET"; then
  pass "the script sets pipefail, so the status survives the tee at the call site"
else
  fail "initrd-flash.sh no longer sets pipefail; get_final_status | tee always exits 0"
fi

echo
if [ "$failures" -eq 0 ]; then
  echo "test-final-status: PASS"
  exit 0
fi
echo "test-final-status: FAIL ($failures)"
exit 1
