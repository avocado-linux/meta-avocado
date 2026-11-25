#!/usr/bin/env bash
# Host test for read_boardinfo_t234() in tegra234-flash-helper.sh: the board-info
# read over USB recovery mode must set CHIP_SKU and RAMCODE on success and exit
# non-zero, saying why, when the read fails or returns without writing
# chip_info.bin_bak.
#
# The function is extracted rather than sourced: the helper is a script, not a
# library, and sourcing it would run the flash. It exits on failure, so every
# call runs in a subshell.

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

# The globals the helper sets before the call; the stub python3 ignores them.
flashappname=tegraflash.py
inst_args=
skipuid=
keyargs=
EMC_FUSE_DEV_PARAMS=dev_params.cfg
DEVICE_CONFIG=device.cfg
MISC_CONFIG=misc.cfg
cvm_bin=cvm.bin
custinfo_out=custinfo.bin

# $1 exit status of the stand-in tegraflash read, $2 "write" to create
# chip_info.bin_bak the way the real read does as a side effect
setup() {
  rm -rf "$w/work" "$w/tools" "$w/stubs"
  mkdir -p "$w/work" "$w/tools" "$w/stubs"
  cat >"$w/stubs/python3" <<STUB
#!/bin/sh
[ "$2" = write ] && : >chip_info.bin_bak
exit $1
STUB
  cat >"$w/tools/chkbdinfo" <<'STUB'
#!/bin/sh
case "$1" in
  -C) echo " D0 " ;;
  -R) echo "ramcode:0:0:0000001d" ;;
esac
STUB
  chmod +x "$w/stubs/python3" "$w/tools/chkbdinfo"
}

# Runs the function in a subshell and leaves its status in $rc, its stderr in
# $err, and the two globals it sets in $sku and $ram.
run() {
  out=$(
    cd "$w/work" || exit 99
    PATH="$w/stubs:$PATH"
    here=$w/tools
    CHIP_SKU=
    RAMCODE=
    read_boardinfo_t234 2>"$w/err"
    rc=$?
    echo "sku=$CHIP_SKU ram=$RAMCODE"
    exit $rc
  )
  rc=$?
  err=$(cat "$w/err")
  sku=$(echo "$out" | sed -n 's/^sku=\([^ ]*\) .*/\1/p')
  ram=$(echo "$out" | sed -n 's/.* ram=//p')
}

setup 0 write
run
{ [ $rc -eq 0 ] && [ "$sku" = D0 ] && [ "$ram" = 13 ]; } \
  && ok "a successful read exits 0 and sets CHIP_SKU and RAMCODE" \
  || bad "success: rc=$rc sku=$sku ram=$ram err=$err"

setup 1 write
run
{ [ $rc -eq 1 ] && echo "$err" | grep -q 'could not retrieve EEPROM board information'; } \
  && ok "a failed read exits 1 and says the EEPROM board information could not be retrieved" \
  || bad "read failed: rc=$rc err=$err"

setup 0 nowrite
run
{ [ $rc -eq 1 ] && echo "$err" | grep -q 'chip_info.bin_bak missing'; } \
  && ok "a read that writes no chip_info.bin_bak exits 1 and names the missing file" \
  || bad "file missing: rc=$rc err=$err"

echo
expected=3
echo "checks: $total/$expected run (passed: $pass  failed: $fail)"
[ $fail -eq 0 ] && [ "$total" -eq "$expected" ]
