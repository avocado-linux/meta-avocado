#!/usr/bin/env bash
# Host test for the RCM boot step of initrd-flash.sh: a failed tegrarcm_v2 upload
# must fail the step and say why. The generated rcm-boot.sh used to end in
# `cd "$oldwd"`, so it exited 0 whatever tegrarcm_v2 returned, the flash went on
# to wait for a USB storage device the flash kernel never exported, and the real
# "might be timeout in USB write" line stayed in the log file.
#
# The functions are extracted rather than sourced: initrd-flash.sh is a script,
# not a library, and sourcing it would run the flash.
# ok() and bad() cannot fail, so `A && ok || bad` is an if-then-else here.
# shellcheck disable=SC2015
set -u
set -o pipefail
here=$(cd "$(dirname "$0")" && pwd)
script=$here/../tegra-helper-scripts/initrd-flash.sh
w=$(mktemp -d)
trap 'rm -rf "$w"' EXIT
pass=0
fail=0
ok() {
  echo "  ok   - $1"
  pass=$((pass + 1))
}
bad() {
  echo "  FAIL - $1"
  fail=$((fail + 1))
}

for fn in create_rcm_boot_script run_rcm_boot_t234 report_rcm_boot_failure; do
  eval "$(awk -v f="$fn" '$0 ~ "^"f"\\(\\) \\{" {p=1} p {print} p && /^\}/ {exit}' "$script")"
  if ! declare -f "$fn" >/dev/null; then
    echo "FAIL - could not extract $fn from $script"
    exit 1
  fi
done

# $1 exit status of the stand-in tegrarcm_v2, $2 what it prints first
setup() {
  rm -rf "$w/work" "$w/tools"
  mkdir -p "$w/work/rcmboot_blob" "$w/tools"
  cat >"$w/tools/tegrarcm_v2" <<STUB
#!/bin/sh
echo "$2"
exit $1
STUB
  chmod +x "$w/tools/tegrarcm_v2"
  echo "./tegrarcm_v2 --rcm blob.bin" >"$w/work/rcmboot_blob/rcmbootcmd.txt"
  here=$w/tools
  BR_CID=
  cd "$w/work" || exit 1
  create_rcm_boot_script
}

setup 3 "ERROR: might be timeout in USB write."
msg=$(run_rcm_boot_t234 2>&1)
rc=$?
[ $rc -ne 0 ] && ok "run_rcm_boot_t234 fails when tegrarcm_v2 fails" || bad "t234 rc=$rc: $msg"
echo "$msg" | grep -q 'ERR: RCM boot failed' \
  && echo "$msg" | grep -q 'might be timeout in USB write' \
  && ok "t234 failure names the RCM boot and the real USB-write error" \
  || bad "t234 message: $msg"

setup 3 "ERROR: might be timeout in USB write."
BR_CID=0x1234
msg=$(run_rcm_boot_t234 2>&1)
rc=$?
{ [ $rc -ne 0 ] && echo "$msg" | grep -q 'ERR: RCM boot failed'; } \
  && ok "a failure with BR_CID already set is reported too" || bad "BR_CID set: rc=$rc $msg"

setup 0 "BR_CID: 0x1234"
msg=$(run_rcm_boot_t234 2>&1)
rc=$?
{ [ $rc -eq 0 ] && ! echo "$msg" | grep -q 'ERR:'; } \
  && ok "a successful upload still succeeds, silently" || bad "success: rc=$rc $msg"

setup 0 "BR_CID: 0x1234"
run_rcm_boot_t234 >/dev/null 2>&1
[ "$BR_CID" = " 0x1234" ] && ok "BR_CID is still read from the upload output" || bad "BR_CID='$BR_CID'"

echo
echo "passed: $pass  failed: $fail"
[ $fail -eq 0 ]
