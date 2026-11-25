#!/usr/bin/env bash
# Host test for read_boardinfo_t234() in tegra234-flash-helper.sh: the board-info
# read over USB recovery mode must set CHIP_SKU and RAMCODE on success, and must
# stop the helper with status 3, saying the board did not answer, when the read
# fails or leaves no usable chip_info.bin_bak. The ramcode failure after a good
# read keeps status 1.
#
# The function is extracted rather than sourced: the helper is a script, not a
# library, and sourcing it would run the flash. It exits on failure, so every
# call runs in a subshell and a call that returned instead of exiting is seen.

# ok and bad only echo and increment, so `cond && ok || bad` cannot run both.
# The globals below are read by the extracted function, not by this file.
# shellcheck disable=SC2015,SC2034
set -u
here=$(cd "$(dirname "$0")" && pwd)
script=$here/../tegra-helper-scripts/tegra234-flash-helper.sh
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

eval "$(awk '/^read_boardinfo_t234\(\) \{/,/^\}/' "$script")"
if ! declare -f read_boardinfo_t234 >/dev/null; then
  echo "FAIL - could not extract read_boardinfo_t234 from $script"
  exit 1
fi

# The globals the helper sets before the call; the stub python3 records them.
flashappname=tegraflash.py
inst_args="--instance 1"
skipuid="--skipuid"
keyargs="--key k.pem"
EMC_FUSE_DEV_PARAMS=dev_params.cfg
DEVICE_CONFIG=device.cfg
MISC_CONFIG=misc.cfg
cvm_bin=cvm.bin
custinfo_out=custinfo.bin
STALE=

setup() {
  rm -rf "${w:?}/work" "${w:?}/tools" "${w:?}/stubs"
  mkdir -p "$w/work" "$w/tools" "$w/stubs"
  cat >"$w/stubs/python3" <<'STUB'
#!/bin/sh
printf '[%s]' "$@" >python3.args
case "$STUB_PY_WRITE" in
  data) echo data >chip_info.bin_bak ;;
  empty) : >chip_info.bin_bak ;;
esac
exit "$STUB_PY_RC"
STUB
  cat >"$w/tools/chkbdinfo" <<'STUB'
#!/bin/sh
case "$1" in
  -C) echo " D0 " ;;
  -R) printf '%s' "$STUB_RAMCODE" ;;
esac
STUB
  chmod +x "$w/stubs/python3" "$w/tools/chkbdinfo"
}

# $1 exit status of the stand-in tegraflash read, $2 what it leaves behind
# (data, empty or none), $3 what chkbdinfo -R prints. Runs the function in a
# subshell and leaves its status in $rc, its stderr in $err, and in $returned
# the line printed only when the call returned instead of exiting.
run() {
  setup
  returned=$(
    cd "$w/work" || exit 99
    [ -z "$STALE" ] || echo stale >chip_info.bin_bak
    export PATH="$w/stubs:$PATH" STUB_PY_RC=$1 STUB_PY_WRITE=$2 STUB_RAMCODE=$3
    here=$w/tools
    CHIP_SKU=
    RAMCODE=
    read_boardinfo_t234 2>"$w/err"
    echo "returned sku=$CHIP_SKU ram=$RAMCODE"
  )
  rc=$?
  err=$(cat "$w/err")
}

# Both unanswered-read paths must say the board did not answer, how to recover
# it, and keep the branch that fired in the first line. "signing" would blame a
# step that never started.
unanswered() {
  { echo "$err" | grep -q 'did not answer the board-info read over USB recovery mode (RCM)' \
    && echo "$err" | grep -qi 'power the board off' \
    && echo "$err" | grep -qi 'recovery mode from cold' \
    && echo "$err" | grep -qi 'hold the recovery button while powering on' \
    && ! echo "$err" | grep -qi 'signing'; }
}

# $1 text the first stderr line must contain. An exit leaves no "returned" line.
stopped_with_3() {
  { [ $rc -eq 3 ] && [ -z "$returned" ] && unanswered && echo "$err" | sed -n 1p | grep -q "$1"; }
}

run 0 data 'ramcode:0:0:0000001d'
{ [ $rc -eq 0 ] && [ "$returned" = "returned sku=D0 ram=13" ] && [ -z "$err" ]; } \
  && ok "a successful read exits 0 and sets CHIP_SKU and RAMCODE" \
  || bad "success: rc=$rc returned=$returned err=$err"

# The stub records one bracketed word per argument, so a merged, split or empty
# word is seen. The three argument lists are non-empty here and empty below.
words() { printf '[%s]' "$@"; }
cmd='readfuses fuse_t234.bin fuse_t234.xml; dump eeprom cvm cvm.bin; dump try_custinfo custinfo.bin; reboot recovery'
args=$(cat "$w/work/python3.args" 2>/dev/null)
want=$(words tegraflash.py --instance 1 --chip 0x23 --skipuid --key k.pem --applet mb1_t234_prod.bin --dev_params dev_params.cfg --cfg readinfo_t234_min_prod.xml --device_config device.cfg --misc_config misc.cfg --bins "mb2_applet applet_t234.bin" --cmd "$cmd")
[ "$args" = "$want" ] \
  && ok "the read runs the tegraflash command the helper always ran, one word per argument" \
  || bad "tegraflash arguments changed: $args"

inst_args=
skipuid=
keyargs=
run 0 data 'ramcode:0:0:0000001d'
args=$(cat "$w/work/python3.args" 2>/dev/null)
want=$(words tegraflash.py --chip 0x23 --applet mb1_t234_prod.bin --dev_params dev_params.cfg --cfg readinfo_t234_min_prod.xml --device_config device.cfg --misc_config misc.cfg --bins "mb2_applet applet_t234.bin" --cmd "$cmd")
[ "$args" = "$want" ] \
  && ok "empty argument lists add no empty word to the tegraflash command" \
  || bad "empty lists changed the command: $args"

run 1 data 'ramcode:0:0:0000001d'
stopped_with_3 'read failed' \
  && ok "a failed read exits 3, names the unanswered read and the cold recovery entry" \
  || bad "read failed: rc=$rc returned=$returned err=$err"

run 0 none 'ramcode:0:0:0000001d'
stopped_with_3 'chip information file missing' \
  && ok "a read that writes no chip_info.bin_bak exits 3 with the same guidance" \
  || bad "file missing: rc=$rc returned=$returned err=$err"

STALE=1
run 0 none 'ramcode:0:0:0000001d'
STALE=
stopped_with_3 'chip information file missing' \
  && ok "a chip_info.bin_bak left by an earlier read does not stand in for this one" \
  || bad "stale file: rc=$rc returned=$returned err=$err"

run 0 empty 'ramcode:0:0:0000001d'
stopped_with_3 'chip information file missing or empty' \
  && ok "an empty chip_info.bin_bak exits 3 with the same guidance" \
  || bad "empty file: rc=$rc returned=$returned err=$err"

run 0 data ''
{ [ $rc -eq 1 ] && [ -z "$returned" ] \
  && echo "$err" | grep -q 'ramcode could not be extracted from chip info' \
  && ! echo "$err" | grep -q 'did not answer'; } \
  && ok "a ramcode that cannot be extracted after a good read keeps exit 1" \
  || bad "ramcode: rc=$rc returned=$returned err=$err"

echo
expected=8
echo "checks: $total/$expected run (passed: $pass  failed: $fail)"
[ $fail -eq 0 ] && [ "$total" -eq "$expected" ]
