#!/usr/bin/env bash
#
# The Step 4 export-timeout message in initrd-flash.sh.
#
# Observed 2026-08-14 on a Jetson Orin Nano. The target printed
# "Export of mmcblk0 failed" to its debug UART and then stopped
# re-enumerating; the host printed:
#
#     ERR: Timeout waiting for exported storage device mmcblk0 after 120s
#     Available devices:
#       /dev/sda: 7630885MB, vendor: ATA
#       /dev/sdb: 9537536MB, vendor: ATA
#       /dev/sdc: 1907729MB, vendor: ATA
#
# Every line of that points at the host. The three disks listed are the host's
# own SATA drives and have nothing to do with the flash. Nothing says the target
# was asked to export something and refused, and nothing points at the debug
# UART, which is the only place the reason exists - the target never re-exports
# the flashpkg LUN that initrd-flash.sh:937-945 reads logs from, so the host
# cannot recover the message itself.
#
# This runs the real timeout handler by extracting it from the script, rather
# than asserting on source text, so a reworded message that still fails to name
# the target is caught.

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

echo "test-export-timeout-message: $TARGET"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Lift wait_for_exported_storage out of the script. Sourcing the script whole
# would run the flash.
awk '/^wait_for_exported_storage\(\) \{/{f=1} f{print} f&&/^\}$/{exit}' \
  "$TARGET" > "$work/fn.sh"

if [ ! -s "$work/fn.sh" ]; then
  fail "could not extract wait_for_exported_storage from the script"
  echo "test-export-timeout-message: FAIL (1)"
  exit 1
fi

# Stubs for the helpers the function calls, so it runs standalone.
cat > "$work/harness.sh" <<'EOF'
get_device_property() { echo "ATA"; }
check_usb_instance=no
EOF
cat "$work/fn.sh" >> "$work/harness.sh"
cat >> "$work/harness.sh" <<'EOF'
# session id, device name, usb instance, min size, 1s timeout
wait_for_exported_storage "deadbeef" "mmcblk0" "" 1000 1
EOF

out="$(bash "$work/harness.sh" 2>&1)"
rc=$?

if [ "$rc" -ne 0 ]; then
  pass "the handler still fails on timeout"
else
  fail "handler returned success on timeout"
fi

# The requested device must appear as something the TARGET was asked for.
if printf '%s\n' "$out" | grep -qi "target" && printf '%s\n' "$out" | grep -q "mmcblk0"; then
  pass "the message names the target and the device it was asked to export"
else
  fail "message does not attribute the failure to the target: $(printf '%s' "$out" | head -4)"
fi

# The one place the reason exists has to be named.
if printf '%s\n' "$out" | grep -qiE 'uart|serial|console'; then
  pass "the message points at the debug console for the reason"
else
  fail "message does not point at the serial console"
fi

echo
if [ "$failures" -eq 0 ]; then
  echo "test-export-timeout-message: PASS"
  exit 0
fi
echo "test-export-timeout-message: FAIL ($failures)"
exit 1
