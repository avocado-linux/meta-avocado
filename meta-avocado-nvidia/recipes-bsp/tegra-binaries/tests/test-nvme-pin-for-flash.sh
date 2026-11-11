#!/usr/bin/env bash
#
# Regression test for nvme-pin-for-flash: the target-side half of the NVMe
# flash target knob (ROOTFS_NVME_PCI). Given a PCIe address it must leave that
# controller as nvme0n1 and every other NVMe controller unbound, so NVIDIA's
# unified flash, which writes nvme0n1 by name, writes that disk.
#
# Runs the script against a fake sysfs. A background reader plays the kernel:
# it records every write to the driver's bind/unbind files and, on bind, gives
# the controller the lowest free nvme index, as the nvme driver does.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIN="$SCRIPT_DIR/../tegra-helper-scripts/nvme-pin-for-flash.sh"
failures=0

pass() { printf '  ok   %s\n' "$1"; }
fail() {
  printf '  FAIL %s\n' "$1"
  failures=$((failures + 1))
}

echo "test-nvme-pin-for-flash: $PIN"

# setup <sys> <addr>=<index or -> ...  ("-": present but unbound)
setup() {
  local sys="$1" spec addr idx
  shift
  mkdir -p "$sys/bus/pci/drivers/nvme"
  for spec in "$@"; do
    addr="${spec%%=*}"
    idx="${spec#*=}"
    mkdir -p "$sys/bus/pci/devices/$addr/nvme"
    if [ "$idx" != "-" ]; then
      mkdir -p "$sys/bus/pci/devices/$addr/nvme/nvme$idx/nvme${idx}n1"
      ln -s "../../devices/$addr" "$sys/bus/pci/drivers/nvme/$addr"
    fi
  done
  mkfifo "$sys/bus/pci/drivers/nvme/bind" "$sys/bus/pci/drivers/nvme/unbind"
}

# fake_kernel <sys> <log>: serve bind/unbind until killed, one loop per file
# so a second write to either never waits on the other.
fake_kernel() {
  local sys="$1" log="$2" drv="$1/bus/pci/drivers/nvme"
  (
    while read -r a <"$drv/unbind"; do
      echo "unbind $a" >>"$log"
      rm -f "$drv/$a"
      rm -rf "$sys/bus/pci/devices/$a/nvme/"nvme*
    done
  ) &
  (
    while read -r a <"$drv/bind"; do
      # A real sysfs write returns after the driver is done; a FIFO write
      # returns once the line is read. Let an unbind written just before
      # finish first, as it would have in the kernel.
      sleep 0.3
      echo "bind $a" >>"$log"
      n=0
      while ls -d "$sys"/bus/pci/devices/*/nvme/nvme$n >/dev/null 2>&1; do n=$((n + 1)); done
      mkdir -p "$sys/bus/pci/devices/$a/nvme/nvme$n/nvme${n}n1"
      ln -sf "../../devices/$a" "$drv/$a"
    done
  ) &
  wait
}

# run_pin <addr> <spec...>: results in pin_rc, pin_out, kernel_log, sys
run_pin() {
  local addr="$1" kpid
  shift
  sys=$(mktemp -d)
  setup "$sys" "$@"
  : >"$sys/kernel.log"
  fake_kernel "$sys" "$sys/kernel.log" &
  kpid=$!
  pin_out=$(SYSFS="$sys" NVME_PIN_WAIT=3 sh "$PIN" "$addr" 2>&1)
  pin_rc=$?
  stop_kernel "$kpid"
  kernel_log=$(cat "$sys/kernel.log")
}

cleanup() { rm -rf "$sys"; }

# Kill the fake kernel and its two readers by PID.
stop_kernel() {
  local k="$1" c g
  for c in $(ps -o pid= --ppid "$k" 2>/dev/null); do
    for g in $(ps -o pid= --ppid "$c" 2>/dev/null); do kill "$g" 2>/dev/null; done
    kill "$c" 2>/dev/null
  done
  kill "$k" 2>/dev/null
  wait "$k" 2>/dev/null
}

# --- 1. target already nvme0: the other is unbound, the target left alone ---
run_pin 0005:01:00.0 0005:01:00.0=0 0003:01:00.0=1
if [ "$pin_rc" -eq 0 ] && grep -qx 'NVME-PINNED 0005:01:00.0 nvme0n1' <<<"$pin_out" \
  && grep -qx 'unbind 0003:01:00.0' <<<"$kernel_log" && ! grep -q '0005:01:00.0' <<<"$kernel_log"; then
  pass "target already nvme0: other controller unbound, target untouched"
else
  fail "target already nvme0: rc=$pin_rc out=[$pin_out] kernel=[$(tr '\n' ';' <<<"$kernel_log")]"
fi
cleanup

# --- 2. target came up second: it is rebound and takes nvme0 ----------------
run_pin 0005:01:00.0 0003:01:00.0=0 0005:01:00.0=1
if [ "$pin_rc" -eq 0 ] && grep -qx 'NVME-PINNED 0005:01:00.0 nvme0n1' <<<"$pin_out" \
  && [ "$(head -1 <<<"$kernel_log")" = "unbind 0003:01:00.0" ] \
  && grep -qx 'bind 0005:01:00.0' <<<"$kernel_log" \
  && [ -e "$sys/bus/pci/devices/0005:01:00.0/nvme/nvme0/nvme0n1" ] \
  && [ ! -e "$sys/bus/pci/drivers/nvme/0003:01:00.0" ]; then
  pass "target was nvme1: other unbound first, target rebound as nvme0n1"
else
  fail "target was nvme1: rc=$pin_rc out=[$pin_out] kernel=[$(tr '\n' ';' <<<"$kernel_log")]"
fi
cleanup

# --- 3. the target never comes back as nvme0n1: fail -------------------------
# A third controller holding nvme0 that the script does not know to unbind
# cannot happen through the driver, so model it with an unbound target that
# the fake kernel would bind as nvme1 behind a leftover nvme0 directory.
sys=$(mktemp -d)
setup "$sys" 0005:01:00.0=- 0007:01:00.0=-
mkdir -p "$sys/bus/pci/devices/0007:01:00.0/nvme/nvme0"
: >"$sys/kernel.log"
fake_kernel "$sys" "$sys/kernel.log" &
kpid=$!
pin_out=$(SYSFS="$sys" NVME_PIN_WAIT=2 sh "$PIN" 0005:01:00.0 2>&1)
pin_rc=$?
stop_kernel "$kpid"
if [ "$pin_rc" -ne 0 ] && ! grep -q 'NVME-PINNED' <<<"$pin_out"; then
  pass "target not nvme0n1 after the wait: fails without claiming a pin"
else
  fail "unpinned target reported success: rc=$pin_rc out=[$pin_out]"
fi
cleanup

# --- 4. bad input -------------------------------------------------------------
sys=$(mktemp -d)
setup "$sys" 0005:01:00.0=0
for bad in "" "5:1:0.0" "0005:01:00" "../../x"; do
  if ! out=$(SYSFS="$sys" NVME_PIN_WAIT=1 sh "$PIN" "$bad" 2>&1) && ! grep -q NVME-PINNED <<<"$out"; then
    pass "address '$bad' refused"
  else
    fail "address '$bad' accepted: $out"
  fi
done
if ! out=$(SYSFS="$sys" NVME_PIN_WAIT=1 sh "$PIN" 0009:01:00.0 2>&1) && grep -q 'no PCI device' <<<"$out"; then
  pass "an address with no device is refused"
else
  fail "missing device accepted: $out"
fi
cleanup

echo
if [ "$failures" -eq 0 ]; then
  echo "test-nvme-pin-for-flash: PASS"
  exit 0
fi
echo "test-nvme-pin-for-flash: FAIL ($failures)"
exit 1
