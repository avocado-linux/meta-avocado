#!/usr/bin/env bash
#
# Regression test for nvdd-pin-gate: while initrd-flash pins the NVMe flash
# target, bootburn's writers run in parallel through this stand-in for nvdd.
# No write may run before the pin reports, and a failed or missing pin must
# refuse the write instead of letting it land on whichever disk is nvme0n1.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATE="$SCRIPT_DIR/../tegra-helper-scripts/nvdd-pin-gate.sh"
failures=0
pass() { printf '  ok   %s\n' "$1"; }
fail() {
  printf '  FAIL %s\n' "$1"
  failures=$((failures + 1))
}

echo "test-nvdd-pin-gate: $GATE"

setup() {
  d=$(mktemp -d)
  printf '#!/bin/sh\necho "real nvdd $*" >>"%s/writes"\n' "$d" >"$d/nvdd.real"
  chmod +x "$d/nvdd.real"
}

# --- 1. a write waits for the pin, then runs the real nvdd with its args -----
setup
NVDD_GATE_DIR="$d" NVDD_GATE_WAIT=10 sh "$GATE" --device /dev/nvme0n1 --x 1 >"$d/out" 2>&1 &
g=$!
sleep 2
if [ -e "$d/writes" ]; then
  fail "the write ran before the pin reported"
else
  pass "no write before the pin reports"
fi
touch "$d/nvme-pinned"
wait "$g"
rc=$?
if [ "$rc" -eq 0 ] && grep -qx 'real nvdd --device /dev/nvme0n1 --x 1' "$d/writes"; then
  pass "after the pin, the real nvdd runs with the same arguments"
else
  fail "after the pin: rc=$rc writes=[$(cat "$d/writes" 2>/dev/null)]"
fi
rm -rf "$d"

# --- 2. a failed pin refuses the write ---------------------------------------
setup
touch "$d/nvme-pin-failed"
if ! NVDD_GATE_DIR="$d" NVDD_GATE_WAIT=10 sh "$GATE" --device /dev/nvme0n1 >/dev/null 2>&1 \
  && [ ! -e "$d/writes" ]; then
  pass "a failed pin refuses the write"
else
  fail "a failed pin let the write through"
fi
rm -rf "$d"

# --- 3. no pin within the wait refuses the write -----------------------------
setup
if ! NVDD_GATE_DIR="$d" NVDD_GATE_WAIT=1 sh "$GATE" --device /dev/nvme0n1 >/dev/null 2>&1 \
  && [ ! -e "$d/writes" ]; then
  pass "no pin within NVDD_GATE_WAIT refuses the write"
else
  fail "a missing pin let the write through"
fi
rm -rf "$d"

echo
if [ "$failures" -eq 0 ]; then
  echo "test-nvdd-pin-gate: PASS"
  exit 0
fi
echo "test-nvdd-pin-gate: FAIL ($failures)"
exit 1
