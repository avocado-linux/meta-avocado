#!/usr/bin/env bash
# Host test for stone-provision-uuu-emmc.sh: the checks that stand between "an
# NXP board is on the bus" and an eMMC write. lsusb, uuu, fwup and fw_setenv are
# PATH stubs; the disk image already exists, so no real tool touches anything.
# The stub uuu records its argv and writes nothing. Cases that need a terminal
# run under util-linux script(1), which gives the script a pty on stdin.
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts, so bad runs only when the check failed
set -u
here=$(cd "$(dirname "$0")" && pwd)
script_src=$(readlink -f "${1:-$here/../stone-provision-uuu-emmc.sh}")
lib_src=$(readlink -f "$here/../../../../meta-avocado-distro/stone/avocado-safe-disk.sh")
pty_src=$(readlink -f "$here/../../../../meta-avocado-distro/stone/tests/pty-run.sh")
# shellcheck source=/dev/null # sibling test helper
. "$pty_src"
# No dot in the template: the script derives the image name with ${file%%.*},
# which cuts at the first dot anywhere in the path, directories included.
w=$(mktemp -d /tmp/uuu-emmc-test-XXXXXX)
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

for tool in jq script; do
  command -v "$tool" >/dev/null || {
    echo "SKIP: $tool not installed"
    exit 0
  }
done

mkdir -p "$w/bin" "$w/build" "$w/data" "$w/st" "$w/run"
# The script sources the library from its own directory, as in the stone data dir.
cp "$script_src" "$w/run/stone-provision-uuu-emmc.sh"
cp "$lib_src" "$w/run/avocado-safe-disk.sh"
script=$w/run/stone-provision-uuu-emmc.sh

# lsusb prints st/lsusb; uuu -lsusb prints st/uuu-list; any other uuu call is
# the flash and is recorded in log.
cat >"$w/bin/lsusb" <<S
#!/bin/bash
# Like the real tool, \`-d vid:\` keeps only matching lines.
if [ "\$1" = -d ]; then grep -F " ID \$2" "$w/st/lsusb"; else cat "$w/st/lsusb"; fi
S
cat >"$w/bin/uuu" <<S
#!/bin/bash
if [ "\$1" = -lsusb ]; then
  printf 'uuu (Universal Update Utility) stub\n\nConnected Known USB Devices\n\tPath\t Chip\t Pro\t Vid\t Pid\t BcdVersion\t Serial_no\n\t====================================================================\n'
  cat "$w/st/uuu-list"
  exit 0
fi
echo "uuu \$*" >> "$w/log"
S
cat >"$w/bin/fw_setenv" <<S
#!/bin/bash
echo "fw_setenv \$*" >> "$w/log"
S
cat >"$w/bin/fwup" <<S
#!/bin/bash
echo "fwup \$*" >> "$w/log"
S
chmod +x "$w/bin/"*

cat >"$w/manifest.json" <<'J'
{
  "storage_devices": {"rootdisk": {"out": "avocado-os-test.fwup", "images": {"imx_boot": "imx-boot"}}},
  "provision": {"profiles": {"uuu-emmc": {"config": {"emmc_uboot_dev": "2", "emmc_mmcblk": "2"}}}}
}
J
: >"$w/build/avocado-os-test.img"
: >"$w/data/imx-boot"

NXP_A='Bus 001 Device 007: ID 1fc9:014e NXP Semiconductors SE Blank M3'
NXP_B='Bus 003 Device 004: ID 1fc9:0146 NXP Semiconductors SE Blank 8MP'
OTHER='Bus 002 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub'
UUU_A=$(printf '\t1:2\t MX8MP\t SDPS\t 0x1fc9\t 0x0146\t 0x0001\t')
UUU_B=$(printf '\t3:1-4\t MX93\t SDPS\t 0x1fc9\t 0x014e\t 0x0001\t')

# run STDIN-MODE FORCE [VAR=value...]: STDIN-MODE is "tty:<typed>" (pty, answer
# fed in) or "pipe" (stdin is not a terminal). FORCE is "" for unset. Output
# lands in st/out and the exit status in st/rc.
run() {
  local mode=$1 force=$2 typed
  shift 2
  : >"$w/log"
  local env=(env PATH="$w/bin:$PATH" AVOCADO_STONE_MANIFEST="$w/manifest.json"
    AVOCADO_STONE_BUILD_DIR="$w/build" AVOCADO_STONE_DATA_DIR="$w/data")
  [ -n "$force" ] && env+=(AVOCADO_PROVISION_FORCE="$force")
  env+=("$@")
  case "$mode" in
    tty:*)
      typed=${mode#tty:}
      run_with_tty "$typed\n" "${env[@]}" bash "$script" >"$w/st/out" 2>&1
      ;;
    pipe)
      "${env[@]}" bash "$script" </dev/null >"$w/st/out" 2>&1
      ;;
  esac
  echo $? >"$w/st/rc"
}
rc() { cat "$w/st/rc"; }
out_has() { grep -qF -- "$1" "$w/st/out"; }
flashed() { grep -q '^uuu ' "$w/log"; }

echo "case: no NXP device -> refuse with boot-mode hint"
# The script waits 60s for a device; shorten via a sleep stub.
cat >"$w/bin/sleep" <<'S'
#!/bin/bash
exit 0
S
chmod +x "$w/bin/sleep"
printf '%s\n' "$OTHER" >"$w/st/lsusb"
: >"$w/st/uuu-list"
run pipe ""
[ "$(rc)" -ne 0 ] && ! flashed && out_has "No NXP device detected" && out_has "boot-mode switches" && ok "refused, uuu not run" || bad "zero devices: rc=$(rc), flashed=$(flashed && echo y || echo n)"

echo "case: one device, force=1 -> pinned with -m, identity printed"
printf '%s\n%s\n' "$OTHER" "$NXP_B" >"$w/st/lsusb"
printf '%s\n' "$UUU_A" >"$w/st/uuu-list"
run pipe 1
[ "$(rc)" -eq 0 ] && grep -q '^uuu -v -m 1:2 .*flash_emmc\.uuu$' "$w/log" && ok "uuu called with -m 1:2" || bad "pin: rc=$(rc) log=$(cat "$w/log")"
out_has "1:2" && out_has "1fc9:0146" && ok "device identity printed" || bad "identity missing from output"
grep -q '^SDPS: boot -f imx-boot' "$w/build/uuu/flash_emmc.uuu" && grep -q 'flash -raw2sparse all rootdisk.img' "$w/build/uuu/flash_emmc.uuu" && ok "generated uuu script unchanged in substance" || bad "uuu script content changed"
grep -q '^fw_setenv .* devnum 2$' "$w/log" && grep -q '^fw_setenv .* mmcblk 2$' "$w/log" && ok "U-Boot env patch unchanged" || bad "fw_setenv calls changed"

echo "case: two devices -> refuse, each named by USB path"
printf '%s\n%s\n' "$NXP_A" "$NXP_B" >"$w/st/lsusb"
printf '%s\n%s\n' "$UUU_A" "$UUU_B" >"$w/st/uuu-list"
run pipe 1
[ "$(rc)" -ne 0 ] && ! flashed && out_has "1:2" && out_has "3:1-4" && ok "refused even with force=1, both paths named" || bad "two devices: rc=$(rc) flashed=$(flashed && echo y || echo n)"

echo "case: lsusb sees one device but uuu knows none -> refuse"
printf '%s\n' "$NXP_A" >"$w/st/lsusb"
: >"$w/st/uuu-list"
run pipe 1
[ "$(rc)" -ne 0 ] && ! flashed && ok "refused when uuu cannot see the device" || bad "uuu-blind: rc=$(rc)"

printf '%s\n' "$NXP_B" >"$w/st/lsusb"
printf '%s\n' "$UUU_A" >"$w/st/uuu-list"

echo "case: unset force, terminal, correct retype -> flashes"
run "tty:1:2" ""
[ "$(rc)" -eq 0 ] && flashed && grep -q '^uuu -v -m 1:2 ' "$w/log" && ok "confirmed, flashed" || bad "retype ok: rc=$(rc)"

echo "case: unset force, terminal, wrong retype -> refuse"
run "tty:1:3" ""
[ "$(rc)" -ne 0 ] && ! flashed && out_has "confirmation did not match" && ok "refused, uuu not run" || bad "wrong retype: rc=$(rc)"

echo "case: unset force, no terminal -> proceeds and says confirmation was skipped"
run pipe ""
[ "$(rc)" -eq 0 ] && flashed && out_has "confirmation skipped" && ok "legacy non-interactive behaviour kept, skip announced" || bad "unset/no tty: rc=$(rc)"

echo "case: force=0, no terminal -> refuse"
run pipe 0
[ "$(rc)" -ne 0 ] && ! flashed && out_has "no terminal to confirm on" && ok "refused" || bad "force=0/no tty: rc=$(rc)"

echo "case: force=0, terminal, correct retype -> flashes"
run "tty:1:2" 0
[ "$(rc)" -eq 0 ] && flashed && ok "prompted and flashed" || bad "force=0/tty: rc=$(rc)"

echo "case: force=1 with terminal -> no prompt"
run "tty:wrong" 1
[ "$(rc)" -eq 0 ] && flashed && ok "prompt skipped" || bad "force=1/tty: rc=$(rc)"

echo "case: invalid force value -> refuse before any work"
run pipe yes
[ "$(rc)" -ne 0 ] && ! flashed && ! grep -q '^fw_setenv' "$w/log" && ok "refused up front" || bad "invalid force: rc=$(rc)"

echo "case: lsusb bus/device numbers never satisfy the retype"
# NXP_B is lsusb Bus 003 Device 004; the uuu path is 1:2.
for typed in "004" "3:4" "3:004" "003:004"; do
  run "tty:$typed" ""
  [ "$(rc)" -ne 0 ] && ! flashed && ok "typing '$typed' refused, uuu not run" || bad "lsusb numbers '$typed' accepted: rc=$(rc)"
done

echo "case: two devices, force=1, terminal -> still refuse"
printf '%s\n%s\n' "$NXP_A" "$NXP_B" >"$w/st/lsusb"
printf '%s\n%s\n' "$UUU_A" "$UUU_B" >"$w/st/uuu-list"
run "tty:1:2" 1
[ "$(rc)" -ne 0 ] && ! flashed && ok "force=1 does not select a board" || bad "two boards, force=1/tty: rc=$(rc)"
printf '%s\n' "$NXP_B" >"$w/st/lsusb"
printf '%s\n' "$UUU_A" >"$w/st/uuu-list"

echo "case: dry run -> checks run, uuu command printed, nothing written, no prompt"
run "tty:wrong" "" AVOCADO_PROVISION_DRY_RUN=1
[ "$(rc)" -eq 0 ] && ! flashed && ! grep -q '^fw_setenv\|^fwup' "$w/log" && ok "no uuu, fwup or fw_setenv call" || bad "dry run wrote: rc=$(rc) log=$(cat "$w/log")"
out_has "dry-run: uuu -v -m 1:2 " && ok "uuu command printed with -m and the path" || bad "dry run command missing"
out_has "dry run: nothing was written to 1:2." && ok "closing line names the path" || bad "dry run closing line missing"
tail -1 "$w/st/out" | grep -q 'nothing was written to 1:2\.' && ok "closing line is last" || bad "closing line not last"

echo "case: dry run, two devices -> still refuse"
printf '%s\n%s\n' "$NXP_A" "$NXP_B" >"$w/st/lsusb"
printf '%s\n%s\n' "$UUU_A" "$UUU_B" >"$w/st/uuu-list"
run pipe 1 AVOCADO_PROVISION_DRY_RUN=1
[ "$(rc)" -ne 0 ] && ! flashed && ok "count check runs in a dry run" || bad "dry run two devices: rc=$(rc)"
printf '%s\n' "$NXP_B" >"$w/st/lsusb"
printf '%s\n' "$UUU_A" >"$w/st/uuu-list"

echo "case: dry run, payload missing -> refuse"
mv "$w/data/imx-boot" "$w/data/imx-boot.away"
run pipe 1 AVOCADO_PROVISION_DRY_RUN=1
[ "$(rc)" -ne 0 ] && ! flashed && out_has "imx-boot not found" && ok "payload check runs in a dry run" || bad "dry run payload: rc=$(rc)"
mv "$w/data/imx-boot.away" "$w/data/imx-boot"

echo "case: upgrade task -> refuse before waiting for a device"
printf '%s\n' "$OTHER" >"$w/st/lsusb"
: >"$w/st/uuu-list"
run pipe 1 AVOCADO_PROVISION_FWUP_TASK=upgrade
[ "$(rc)" -ne 0 ] && ! flashed && out_has "upgrade" && ! out_has "serial download mode" && ok "refused up front, no device wait" || bad "upgrade: rc=$(rc) out=$(cat "$w/st/out")"
printf '%s\n' "$NXP_B" >"$w/st/lsusb"
printf '%s\n' "$UUU_A" >"$w/st/uuu-list"

echo "case: shared confirmation vectors (terminal rows)"
vec=$here/../../../../meta-avocado-distro/stone/tests/confirm-vectors.tsv
nvec=0
while IFS=$'\t' read -r f term dry outcome; do
  case "$f" in '#'* | force | '') continue ;; esac
  [ "$dry" = no ] || continue
  fv=$f
  case "$f" in '<unset>' | '<empty>') fv="" ;; esac
  if [ "$term" = yes ]; then mode="tty:1:2"; else mode=pipe; fi
  nvec=$((nvec + 1))
  if [ "$f" = bogus ]; then run "$mode" bogus; else run "$mode" "$fv"; fi
  case "$outcome" in
    skip | proceed) [ "$(rc)" -eq 0 ] && flashed && r=ok || r=bad ;;
    retype) [ "$(rc)" -eq 0 ] && flashed && r=ok || r=bad ;;
    refuse) [ "$(rc)" -ne 0 ] && ! flashed && r=ok || r=bad ;;
  esac
  [ "$r" = ok ] && ok "vector force=$f terminal=$term -> $outcome" || bad "vector force=$f terminal=$term -> $outcome (rc=$(rc))"
done <"$vec"
[ "$nvec" -ge 8 ] && ok "vectors read: $nvec" || bad "too few vectors read: $nvec"

echo
total=37
echo "passed=$pass failed=$fail  (checks: $((pass + fail))/$total run)"
[ "$fail" -eq 0 ] && [ $((pass + fail)) -eq "$total" ]
