#!/usr/bin/env bash
#
# Pre-flight checks in stone-provision-tegraflash.sh.
#
# initrd-flash mounts the board's exposed USB storage to write the command
# package and contains no sudo invocations, so provisioning needs CAP_SYS_ADMIN.
# Without it the run signs binaries, boots the board over RCM, and only then
# dies at "ERR: could not mount USB storage for writing flashing commands" -
# which reads as a storage or cable fault, some 40 seconds after the point where
# the real cause was already knowable. Observed 2026-08-14 on a first flash of a
# Jetson Orin Nano.
#
# The check therefore has to fire before any work, not merely before mounting,
# and it has to name privilege as the cause. Both are asserted here.

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

echo "test-preflight-checks: $TARGET"

if [ "$(id -u)" -eq 0 ]; then
  echo "  skip  running as root; cannot exercise the non-root path" >&2
  echo "test-preflight-checks: PASS"
  exit 0
fi

# Deliberately no environment. A check that fires only after the manifest
# variables are dereferenced is too late to be useful, and under `set -u` the
# script would die on the unset variable instead, masking the real cause.
out="$(env -i "$(command -v bash)" "$TARGET" 2>&1)"
rc=$?

if [ "$rc" -ne 0 ]; then
  pass "non-root invocation exits non-zero"
else
  fail "non-root invocation succeeded; the privilege check is absent"
fi

if printf '%s\n' "$out" | grep -qiE 'root|privilege|sudo'; then
  pass "the failure names privilege as the cause"
else
  fail "failure does not mention root/privilege; got: $(printf '%s' "$out" | head -3)"
fi

# The script must not have got far enough to touch the manifest. If it did, the
# operator sees an unset-variable or jq error and learns nothing about privilege.
if printf '%s\n' "$out" | grep -qiE 'AVOCADO_STONE_MANIFEST: unbound|jq:|No such file'; then
  fail "the check runs after the manifest is read; it must be the first thing"
else
  pass "the check fires before any manifest or environment work"
fi

echo
if [ "$failures" -eq 0 ]; then
  echo "test-preflight-checks: PASS"
  exit 0
fi
echo "test-preflight-checks: FAIL ($failures)"
exit 1
