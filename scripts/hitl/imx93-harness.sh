#!/usr/bin/env bash
# Hardware-in-the-loop assertions for avocado-imx93-frdm.
#
# Exists so that hardware verification produces machine-checkable evidence
# rather than a prose "verify: manual" line. A task whose only evidence is an
# assertion sits below the risk evidence floor, which is what blocked
# uboot-env-lockdown-imx93 from archiving despite the work being done and the
# board being driven by hand.
#
# Rig, and all three values are load-bearing:
#   - KP303 power strip at 192.168.8.202, child index 0 is the imx93 outlet.
#     Index 1 is a DIFFERENT live outlet - do not use it.
#   - tio profile imx93-net, which reaches the console through ser2net on
#     localhost:3001 rather than claiming the tty directly.
#   - The board autoboots unkeyed with a ~2s window, so any byte interrupts it.
set -euo pipefail

KASA_HOST="192.168.8.202"
KASA_INDEX="0"
TIO_PROFILE="imx93-net"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LUA="${HERE}/imx93-harness.lua"

die() {
  printf 'imx93-harness: %s\n' "$*" >&2
  exit 2
}

[ -r "$LUA" ] || die "missing $LUA"
command -v tio >/dev/null 2>&1 || die "tio not on PATH"
command -v kasa >/dev/null 2>&1 || die "kasa not on PATH"

# Power-cycle in the background so tio is ALREADY attached when the autoboot
# window opens. Attaching after the cycle races a 2-second window and loses.
schedule_power_cycle() {
  (
    sleep 2
    kasa --host "$KASA_HOST" --type strip off --child-index "$KASA_INDEX" >/dev/null 2>&1 || true
    sleep 4
    kasa --host "$KASA_HOST" --type strip on --child-index "$KASA_INDEX" >/dev/null 2>&1 || true
  ) &
}

# A full run power-cycles the board and takes minutes, which is well past
# ds-verify's 120s per-command timeout. So the run RECORDS its verdict and a
# task's verify: reads that record instead of driving the board inline. The
# record names the commit it ran against, and the reader requires that commit to
# be an ancestor of HEAD - so a result stays valid across later commits that did
# not touch the board, and a rewritten history invalidates it rather than
# silently vouching for code that never ran.
RESULT_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/avocado-hitl"

record_result() {
  local mode="$1" verdict="$2" commit
  commit="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
  mkdir -p "$RESULT_DIR"
  printf '%s %s %s\n' "$verdict" "$commit" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    >"${RESULT_DIR}/${mode}.result"
}

run_mode() {
  local mode="$1" arg="${2:-}" rc=0
  schedule_power_cycle
  HARNESS_MODE="$mode" HARNESS_ARG="$arg" \
    timeout 300 tio --script-file "$LUA" --script-run once --mute "$TIO_PROFILE" || rc=$?
  if [ "$rc" -eq 0 ]; then record_result "$mode" PASS; else record_result "$mode" FAIL; fi
  return "$rc"
}

# --ums-hold is NOT an assertion and deliberately does not go through run_mode.
# Two reasons, and both would be bugs if it did. It records no verdict, because
# RESULT_DIR entries are read by task verify: lines as evidence that a check ran
# - and "the card was exported" is not a check of anything. And it needs far
# longer than run_mode's 300s: the export must outlive a ~120 MB fwup write, so
# the bound here is the Lua hold's own 40 minutes plus slack, not a task timeout.
run_ums_hold() {
  schedule_power_cycle
  HARNESS_MODE="ums_hold" HARNESS_ARG="" \
    timeout 2700 tio --script-file "$LUA" --script-run once --mute "$TIO_PROFILE"
}

usage() {
  cat >&2 <<'EOF'
usage: imx93-harness.sh <mode>

  --assert-env-lockdown        saved bootcmd is rejected, saved avocado_boot_slot
                               is honoured, and the board still boots
  --assert-slot-boots <a|b>    board boots the named slot to a login prompt
  --assert-uefi-var-persists   a UEFI variable is written, survives a reset, and
                               reads back. Requires firmware with a UEFI variable
                               store; fails with a clear message on firmware that
                               has none. Proves PERSISTENCE, not tamper-resistance.
  --assert-boot-integrity-report
                               on-device reporter emits enforcement + root-of-trust
                                                                 [NOT IMPLEMENTED]

  --ums-hold                   NOT an assertion. Power-cycle, stop at the U-Boot
                               prompt, print `version`, export the SD card over
                               USB mass storage and hold the console until killed
                               so the host can flash the card in place. Records no
                               verdict. Read the printed version BEFORE writing:
                               changing bootloader version and config in one flash
                               is what the runbook warns against, and ums lives in
                               the bootloader being replaced.
EOF
  exit 2
}

case "${1:-}" in
  --assert-env-lockdown) run_mode env_lockdown ;;
  --assert-slot-boots)
    [ "${2:-}" = a ] || [ "${2:-}" = b ] || die "--assert-slot-boots needs a or b"
    run_mode slot_boots "$2"
    ;;
  --assert-uefi-var-persists) run_mode uefi_var_persists ;;
  # Deliberately non-zero rather than a no-op that exits 0. A stub that
  # succeeds is worse than a missing one: it turns an unimplemented check into
  # a passing verify: line, and the task it gates reads as verified.
  --assert-boot-integrity-report)
    die "${1} is not implemented yet - it lands with the reporter in group 4"
    ;;
  --ums-hold) run_ums_hold ;;
  *) usage ;;
esac
