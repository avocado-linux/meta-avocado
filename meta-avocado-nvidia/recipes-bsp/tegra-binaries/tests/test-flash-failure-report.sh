#!/usr/bin/env bash
# Host test for the T234 failure report in initrd-flash.sh: when the signing
# step fails, the flash helper's own exit status must reach the report. Status 3
# (the board did not answer the board-info read) must say so and name the cold
# recovery entry instead of "signing failed", and every failure must print the
# tail of the flash log so the real error is not left in a file nobody opens.
#
# run_t234_step is the code the main flow runs for both steps, so the test runs
# it rather than a copy of it. The functions are extracted rather than sourced:
# initrd-flash.sh is a script, not a library, and sourcing it would run the flash.

# ok and bad only echo and increment, so `cond && ok || bad` cannot run both.
# The globals below are read by the extracted functions, not by this file.
# shellcheck disable=SC2015,SC2034
set -u
set -o pipefail
here=$(cd "$(dirname "$0")" && pwd)
script=$here/../tegra-helper-scripts/initrd-flash.sh
w=$(mktemp -d)
trap 'rm -rf "$w"' EXIT
pass=0
fail=0
total=0
ok() {
  echo "  ok   - $1"
  pass=$((pass + 1))
  total=$((total + 1))
}
bad() {
  echo "  FAIL - $1"
  fail=$((fail + 1))
  total=$((total + 1))
}

for fn in run_t234_step sign_binaries_t234 report_t234_step_failure; do
  eval "$(awk -v f="$fn" '$0 ~ "^"f"\\(\\) \\{" {p=1} p {print} p && /^\}/ {exit}' "$script")"
  if ! declare -f "$fn" >/dev/null; then
    echo "FAIL - could not extract $fn from $script"
    exit 1
  fi
done

# The recovery-boot step is a stand-in whose status the test chooses. With
# STUB_NOISE set it prints one line on each stream, like the helper stand-in.
# shellcheck disable=SC2329
run_rcm_boot_t234() {
  if [ -n "$STUB_NOISE" ]; then
    echo "stub-stdout-line"
    echo "stub-stderr-line" >&2
  fi
  return "$RCM_STUB_STATUS"
}

# The globals sign_binaries_t234 reads on its first helper call. BOARDID and
# FAB are set so it does not wait for a board.
PRESIGNED=
MACHINE=m
BOARDID=3701
FAB=300
BOARDSKU=0005
BOARDREV=
CHIPREV=
CHIP_SKU=D0
ODMDATA=
serial_number=
keyfile=
sbk_keyfile=
instance_args=
DTBFILE=
EMC_BCT=
LNXFILE=
ROOTFS_IMAGE=
FLASH_HELPER=helper.sh
RCM_STUB_STATUS=0
EXTRA_LOG_LINE=
NOISE=
STUB_NOISE=

# $1 exit status of the stand-in flash helper
setup() {
  rm -rf "${w:?}/work" "${w:?}/tools"
  mkdir -p "$w/work" "$w/tools"
  cat >"$w/tools/helper.sh" <<STUB
#!/bin/sh
if [ -n "\$STUB_NOISE" ]; then
  echo "stub-stdout-line"
  echo "stub-stderr-line" >&2
fi
exit $1
STUB
  chmod +x "$w/tools/helper.sh"
  here=$w/tools
  logfile=log.initrd-flash.20260101
}

# $1 step (sign or rcm-boot), $2 exit status of the step's stand-in (the flash
# helper for sign, run_rcm_boot_t234 for rcm-boot), $3 number of lines already
# in the flash log. Runs the real run_t234_step in a subshell, because it exits
# on failure, and leaves the result in $rc, $out and $err. $out holds the line
# "returned" only when the call returned to its caller instead of exiting.
run_flow() {
  setup "$2"
  RCM_STUB_STATUS=$2
  (
    cd "$w/work" || exit 99
    : >"$logfile"
    n=0
    while [ "$n" -lt "$3" ]; do
      n=$((n + 1))
      echo "flash log line $n"
    done >>"$logfile"
    [ -z "$EXTRA_LOG_LINE" ] || printf '%s\n' "$EXTRA_LOG_LINE" >>"$logfile"
    export STUB_NOISE=$NOISE
    run_t234_step "$1"
    echo "returned"
  ) >"$w/out" 2>"$w/err"
  rc=$?
  out=$(cat "$w/out")
  err=$(cat "$w/err")
}

run_flow sign 3 5
{ [ $rc -eq 1 ] \
  && echo "$out" | grep -q 'ERR: device not responding in recovery mode (RCM)' \
  && echo "$out" | grep -q 'enter recovery mode from cold' \
  && ! echo "$out$err" | grep -q 'signing failed'; } \
  && ok "helper status 3 reports the unresponsive device, not a signing failure" \
  || bad "status 3: rc=$rc out=$out err=$err"

run_flow sign 3 5
{ echo "$err" | grep -qF 'log.initrd-flash.20260101' && echo "$err" | grep -q 'flash log line 5'; } \
  && ok "the report names the flash log and prints its tail" \
  || bad "log header: err=$err"

run_flow sign 3 5
grep -q 'ERR: device not responding in recovery mode (RCM)' "$w/work/$logfile" \
  && ok "the ERR line is appended to the flash log" \
  || bad "ERR line missing from the log: $(cat "$w/work/$logfile")"

run_flow sign 1 5
{ echo "$out" | grep -q 'ERR: signing failed at' \
  && ! echo "$out" | grep -q 'device not responding' \
  && echo "$err" | grep -q 'flash log line 5'; } \
  && ok "helper status 1 keeps the signing failed message and prints the tail" \
  || bad "status 1: out=$out err=$err"

run_flow sign 3 5
shown=$(echo "$err" | grep -c '^flash log line ')
{ [ "$shown" -eq 5 ] && echo "$err" | grep -q 'flash log line 1$'; } \
  && ok "a 5-line log is printed whole" || bad "5-line log: shown=$shown err=$err"

run_flow sign 1 100
shown=$(echo "$err" | grep -c '^flash log line ')
{ [ "$shown" -eq 40 ] \
  && echo "$err" | grep -q 'flash log line 61$' \
  && ! echo "$err" | grep -q 'flash log line 60$' \
  && echo "$err" | grep -q 'flash log line 100$'; } \
  && ok "a 100-line log prints exactly its last 40 lines" \
  || bad "100-line log: shown=$shown"

# A board's EEPROM fields reach the log verbatim; an escape sequence in one must
# not reach the terminal, and a tab in the log must survive.
EXTRA_LOG_LINE=$'before\033]0;retitled\007after\001\010\013\014\015\037\177end'
run_flow sign 1 3
EXTRA_LOG_LINE=
{ echo "$err" | grep -qF 'before]0;retitledafterend' \
  && ! printf '%s' "$err" | LC_ALL=C grep -q $'[\001\007\010\013\014\015\033\037\177]'; } \
  && ok "ASCII control characters in the log tail never reach the terminal" \
  || bad "control characters: $(printf '%s' "$err" | od -c | head -5)"

EXTRA_LOG_LINE=$'left\tright'
run_flow sign 1 3
EXTRA_LOG_LINE=
printf '%s' "$err" | grep -qF $'left\tright' \
  && ok "a tab in the log tail survives" || bad "tab lost: $(printf '%s' "$err" | od -c | head -5)"

# A failed step ends the run: the main flow has no guard of its own after the call.
run_flow sign 3 2
{ [ $rc -eq 1 ] && ! echo "$out" | grep -qx 'returned'; } \
  && run_flow rcm-boot 1 2 \
  && { [ $rc -eq 1 ] && ! echo "$out" | grep -qx 'returned'; } \
  && ok "a failed step ends the run instead of returning" \
  || bad "failed step returned: rc=$rc out=$out"

# The recovery-boot step keeps its own message and also prints the tail.
run_flow rcm-boot 1 2
{ [ $rc -eq 1 ] && echo "$out" | grep -q 'ERR: RCM boot failed at' && echo "$err" | grep -q 'flash log line 2$'; } \
  && ok "the recovery-boot step keeps its message and prints the tail" \
  || bad "rcm-boot: rc=$rc out=$out err=$err"

# A step that succeeds is silent and hands control back.
run_flow rcm-boot 0 2
{ [ $rc -eq 0 ] && [ "$out" = "returned" ] && [ -z "$err" ]; } \
  && ok "a successful step reports nothing and returns" \
  || bad "success: rc=$rc out=$out err=$err"

# The step's stdout belongs in the flash log and its stderr on the terminal, for
# both steps. $1 step. The terminal side of `2>&1 >>"$logfile"` is this test's $out.
streams() {
  NOISE=1
  run_flow "$1" 1 2
  NOISE=
  { grep -q 'stub-stdout-line' "$w/work/$logfile" \
    && ! grep -q 'stub-stderr-line' "$w/work/$logfile" \
    && echo "$out" | grep -q 'stub-stderr-line' \
    && ! echo "$out" | grep -q 'stub-stdout-line'; }
}
streams sign && ok "the signing step's stdout goes to the flash log and its stderr to the terminal" \
  || bad "sign streams: out=$out log=$(cat "$w/work/$logfile")"
streams rcm-boot && ok "the recovery-boot step's stdout goes to the flash log and its stderr to the terminal" \
  || bad "rcm-boot streams: out=$out log=$(cat "$w/work/$logfile")"

# A step name nobody handles must not pass for a step that ran.
run_flow bogus 0 1
{ [ $rc -eq 1 ] && echo "$err" | grep -q 'unknown T234 step: bogus' && [ -z "$out" ]; } \
  && ok "an unknown step name is refused" || bad "unknown step: rc=$rc out=$out err=$err"

echo
expected=14
echo "checks: $total/$expected run (passed: $pass  failed: $fail)"
[ $fail -eq 0 ] && [ "$total" -eq "$expected" ]
