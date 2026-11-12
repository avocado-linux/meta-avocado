#!/usr/bin/env bash
# Host test for the wrong-disk guards in stone-provision-sd.sh. Everything that
# touches a disk is a stub (fwup, blockdev, dd, mount, umount, udevadm, stat),
# sysfs is a fake tree, and the "disks" are regular files under a temp dir, so
# a stub that fails to intercept a write lands in that dir and nowhere else.
# The Raspberry Pi script has the same flow; pass it as $1 to run the same cases
# against it:
#   bash meta-avocado-nxp/stone/avocado-imx/tests/test-stone-provision-sd-safe-disk.sh
#   bash meta-avocado-nxp/stone/avocado-imx/tests/test-stone-provision-sd-safe-disk.sh \
#     meta-avocado-raspberrypi/stone/rpi/stone-provision-sd.sh
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts, so bad runs only when the check failed
set -u
here=$(cd "$(dirname "$0")" && pwd)
script_src=$(readlink -f "${1:-$here/../stone-provision-sd.sh}")
lib_src=$(readlink -f "$here/../../../../meta-avocado-distro/stone/avocado-safe-disk.sh")
pty_src=$(readlink -f "$here/../../../../meta-avocado-distro/stone/tests/pty-run.sh")
# shellcheck source=/dev/null # sibling test helper
. "$pty_src"
real_stat=$(command -v stat)
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

USBPATH=pci0000:00/0000:00:14.0/usb1/1-2/1-2:1.0/host6/target6:0:0/6:0:0:0/block
ATAPATH=pci0000:00/0000:00:17.0/ata1/host0/target0:0:0/0:0:0:0/block
mkdisk() { # name path
  mkdir -p "$w/sys/devices/$2/$1/device" "$w/sys/class/block"
  ln -s "../../devices/$2/$1" "$w/sys/class/block/$1"
  echo 7864320 >"$w/sys/devices/$2/$1/size"
  echo "Card Reader" >"$w/sys/devices/$2/$1/device/model"
  : >"$w/dev/$1"
}
mkpart() { # disk path partition
  mkdir -p "$w/sys/devices/$2/$1/$3"
  echo 1 >"$w/sys/devices/$2/$1/$3/partition"
  ln -s "../../devices/$2/$1/$3" "$w/sys/class/block/$3"
  : >"$w/dev/$3"
}

setup() {
  rm -rf "${w:?}/sys" "${w:?}/dev" "${w:?}/st" "${w:?}/bin" "${w:?}/build" "${w:?}/run"
  mkdir -p "$w/dev" "$w/st" "$w/bin" "$w/build" "$w/run"
  cp "$script_src" "$w/run/stone-provision-sd.sh"
  cp "$lib_src" "$w/run/avocado-safe-disk.sh"
  echo '{}' >"$w/manifest.json"
  : >"$w/build/os.aos"
  echo "overlay / overlay rw 0 0" >"$w/st/mounts"
  : >"$w/st/swaps"
  mkdisk sdb "$USBPATH"
  mkpart sdb "$USBPATH" sdb1
  mkdisk sda "$ATAPATH"
  mkpart sda "$ATAPATH" sda1
  echo "$w/dev/sdb,8053063680" >"$w/st/fwup-devices"
  cat >"$w/bin/stat" <<S
#!/bin/bash
if [ "\$1" = -Lc ] && [ "\$2" = %F ]; then
  f=\$(readlink -f -- "\$4")
  case "\$f" in $w/dev/*) [ -f "\$f" ] && { echo "block special file"; exit 0; } ;; esac
fi
exec $real_stat "\$@"
S
  cat >"$w/bin/udevadm" <<S
#!/bin/bash
cat "$w/st/idpath-\$(basename "\$(readlink -f -- "\${@: -1}")")" 2>/dev/null
exit 0
S
  cat >"$w/bin/fwup" <<S
#!/bin/bash
echo "fwup \$*" >> "$w/log"
[ "\$1" = -D ] && cat "$w/st/fwup-devices"
exit 0
S
  cat >"$w/bin/jq" <<S
#!/bin/bash
echo os.aos
S
  cat >"$w/bin/bc" <<S
#!/bin/bash
echo 3.7
S
  cat >"$w/bin/blockdev" <<S
#!/bin/bash
echo 8053063680
S
  cat >"$w/bin/mount" <<S
#!/bin/bash
cat "$w/st/mounts"
S
  # umount drops the lines naming its arguments unless st/umount-noop exists.
  cat >"$w/bin/umount" <<S
#!/bin/bash
echo "umount \$*" >> "$w/log"
[ -e "$w/st/umount-fail" ] && exit 32
[ -e "$w/st/umount-noop" ] && exit 0
: > "$w/st/mounts"
S
  cat >"$w/bin/dd" <<S
#!/bin/bash
exit 0
S
  cat >"$w/bin/sleep" <<S
#!/bin/bash
exit 0
S
  chmod +x "$w/bin/"*
}

# The script's environment. EUID=0 makes the privileged runner exec the stubs
# directly instead of going through sudo.
script_env() {
  env PATH="$w/bin:$PATH" AVOCADO_PROVISION_SYSBLOCK="$w/sys/class/block" \
    AVOCADO_SAFE_DISK_MOUNTS="$w/st/mounts" AVOCADO_SAFE_DISK_SWAPS="$w/st/swaps" AVOCADO_SAFE_DISK_DEVDIR="$w/dev" \
    AVOCADO_SAFE_DISK_EUID=0 \
    AVOCADO_STONE_MANIFEST="$w/manifest.json" AVOCADO_STONE_BUILD_DIR="$w/build" AVOCADO_STONE_DATA_DIR="$w" \
    "$@" bash "$w/run/stone-provision-sd.sh"
}

# $1 = stdin (a pipe), remaining args = extra env assignments for the script.
run() {
  local input=$1
  shift
  : >"$w/log"
  printf '%b' "$input" | script_env "$@" 2>&1
}

# $1 = keystrokes typed at a terminal, remaining args = env assignments.
run_tty() {
  local input=$1
  shift
  : >"$w/log"
  run_with_tty "$input" env PATH="$w/bin:$PATH" AVOCADO_PROVISION_SYSBLOCK="$w/sys/class/block" \
    AVOCADO_SAFE_DISK_MOUNTS="$w/st/mounts" AVOCADO_SAFE_DISK_SWAPS="$w/st/swaps" AVOCADO_SAFE_DISK_DEVDIR="$w/dev" \
    AVOCADO_SAFE_DISK_EUID=0 \
    AVOCADO_STONE_MANIFEST="$w/manifest.json" AVOCADO_STONE_BUILD_DIR="$w/build" AVOCADO_STONE_DATA_DIR="$w" \
    "$@" bash "$w/run/stone-provision-sd.sh"
}
wrote() { grep -q "^fwup -a -u " "$w/log"; }
wrote_to() { grep -q "^fwup -a -u -i $w/build/os.aos -d $1 -t complete" "$w/log"; }
usb() { echo "pci-0000:00:14.0-usb-0:2:1.0-scsi-0:0:0:0" >"$w/st/idpath-$1"; }
sata() { echo "pci-0000:00:17.0-ata-1" >"$w/st/idpath-$1"; }

# --- unattended (AVOCADO_PROVISION_DEVICE): behavior that must not change -----

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb"; } \
  && ok "unattended (FORCE=1): a whole USB disk is written with no prompt and stdin closed" || bad "unattended pass: rc=$rc out=[$out] log=$(cat "$w/log")"
echo "$out" | grep -q "Bus: " \
  && ok "unattended: the bus is shown before the write" || bad "unattended identity: out=[$out]"

setup
sata sda
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sda")
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "not a USB or MMC bus"; } \
  && ok "unattended: a SATA disk is refused before any write" || bad "unattended sata: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb1")
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -qi "partition"; } \
  && ok "unattended: a partition is refused before any write" || bad "unattended partition: rc=$rc out=[$out]"

setup
usb sdb
echo "$w/dev/sdb1 / ext4 rw 0 0" >"$w/st/mounts"
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "running root"; } \
  && ok "unattended: the disk holding / is refused even on a USB bus" || bad "unattended root: rc=$rc out=[$out]"

setup
usb sdb
echo "$w/dev/sdb1 /media/stick vfat rw 0 0" >"$w/st/mounts"
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -eq 0 ] && grep -q "^umount $w/dev/sdb" "$w/log" && wrote_to "$w/dev/sdb"; } \
  && ok "unattended: a mounted partition is still unmounted by the script and the write proceeds" || bad "unattended unmount: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
usb sdb
echo "$w/dev/sdb1 /media/stick vfat rw 0 0" >"$w/st/mounts"
: >"$w/st/umount-noop"
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "mounted or in use"; } \
  && ok "unattended: a partition that is still mounted after the unmount step is refused" || bad "unattended still mounted: rc=$rc out=[$out]"

setup
usb sdb
: >"$w/st/umount-fail"
echo "$w/dev/sdb1 /media/stick vfat rw 0 0" >"$w/st/mounts"
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "Failed to unmount"; } \
  && ok "unattended: a failing unmount still aborts with its existing message" || bad "unattended umount fails: rc=$rc out=[$out]"

# --- interactive: one device from fwup -D ------------------------------------

setup
usb sdb
out=$(run_tty "y\n$w/dev/sdb\n")
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb"; } \
  && ok "interactive: retyping the device path confirms and writes" || bad "interactive pass: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
usb sdb
out=$(run_tty "y\ny\n")
rc=$?
{ [ $rc -ne 0 ] && ! wrote; } \
  && ok "interactive: answering y to the final prompt no longer confirms" || bad "interactive y: rc=$rc out=[$out]"

setup
usb sdb
out=$(run_tty "y\n")
rc=$?
{ [ $rc -ne 0 ] && ! wrote; } \
  && ok "interactive: end of input at the final prompt aborts" || bad "interactive eof: rc=$rc out=[$out]"

setup
usb sdb
out=$(run_tty "y\n" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb"; } \
  && ok "interactive: AVOCADO_PROVISION_FORCE=1 skips the retype" || bad "interactive force: rc=$rc out=[$out]"

setup
sata sda
echo "$w/dev/sda,8053063680" >"$w/st/fwup-devices"
out=$(run_tty "y\n$w/dev/sda\n" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "not a USB or MMC bus"; } \
  && ok "interactive: a SATA disk fwup lists is refused even with FORCE" || bad "interactive sata: rc=$rc out=[$out]"

# --- no device named: the selection is answered from a terminal only ----------

for case_ in "piped y|y\\n|" "empty stdin||" "FORCE=1 piped y|y\\n|AVOCADO_PROVISION_FORCE=1"; do
  IFS='|' read -r label input envs <<<"$case_"
  setup
  usb sdb
  # shellcheck disable=SC2086 # envs is zero or one NAME=value word
  out=$(run "$input" $envs)
  rc=$?
  { [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "no device named and no terminal"; } \
    && ok "no device named, no terminal ($label): refused before any write" || bad "unnamed no tty ($label): rc=$rc out=[$out] log=$(cat "$w/log")"
done

# --- a named device still retypes; only FORCE=1 skips -------------------------

setup
usb sdb
out=$(run_tty "$w/dev/sdb\n" AVOCADO_PROVISION_DEVICE="$w/dev/sdb")
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb"; } \
  && ok "named device: retyping the path at a terminal confirms and writes" || bad "named retype pass: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
usb sdb
out=$(run_tty "/dev/other\n" AVOCADO_PROVISION_DEVICE="$w/dev/sdb")
rc=$?
{ [ $rc -ne 0 ] && ! wrote; } \
  && ok "named device: a wrong retype aborts with no write" || bad "named retype wrong: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=0)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "no terminal to confirm on"; } \
  && ok "named device: no terminal and FORCE=0 refuses and does not write" || bad "named no tty: rc=$rc out=[$out]"

setup
usb sdb
: >"$w/log"
out=$(yes | script_env AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=0 2>&1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote; } \
  && ok "named device: a piped yes never confirms" || bad "named piped yes: rc=$rc out=[$out]"

# --- fwup task ------------------------------------------------------------------

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=1 AVOCADO_PROVISION_FWUP_TASK=upgrade)
rc=$?
{ [ $rc -eq 0 ] && grep -q "^fwup -a -u -i $w/build/os.aos -d $w/dev/sdb -t upgrade" "$w/log"; } \
  && ok "task upgrade: fwup runs -t upgrade" || bad "task upgrade: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=1 AVOCADO_PROVISION_FWUP_TASK=full)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "AVOCADO_PROVISION_FWUP_TASK=full is not valid"; } \
  && ok "task full: refused naming the variable, no write" || bad "task full: rc=$rc out=[$out]"

# --- dry run --------------------------------------------------------------------

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_DRY_RUN=1)
rc=$?
{ [ $rc -eq 0 ] && ! grep -q "^fwup -a" "$w/log" && ! grep -q "^umount" "$w/log" \
  && echo "$out" | grep -q "^dry-run: .*fwup" && echo "$out" | grep -q "dry run: nothing was written to $w/dev/sdb" \
  && echo "$out" | grep -q "Bus: " && ! echo "$out" | grep -q "successfully written"; } \
  && ok "dry run: guards run, the write is printed, nothing is written, no retype asked, exit 0" || bad "dry run: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
usb sdb
echo "$w/dev/sdb1 /media/stick vfat rw 0 0" >"$w/st/mounts"
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_DRY_RUN=1)
rc=$?
{ [ $rc -eq 0 ] && ! grep -q "^umount" "$w/log" && ! grep -q "^fwup -a" "$w/log" && echo "$out" | grep -q "dry-run: umount"; } \
  && ok "dry run: a mounted partition is reported, not unmounted" || bad "dry run mounted: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
sata sda
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sda" AVOCADO_PROVISION_DRY_RUN=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "not a USB or MMC bus"; } \
  && ok "dry run: a SATA disk is still refused" || bad "dry run sata: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_DRY_RUN=2)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "AVOCADO_PROVISION_DRY_RUN=2 is not valid"; } \
  && ok "dry run: a value other than 1 is refused, no write" || bad "dry run invalid: rc=$rc out=[$out]"

total=26
echo
echo "passed: $pass  failed: $fail  (checks: $((pass + fail))/$total run)"
[ "$fail" -eq 0 ] && [ $((pass + fail)) -eq "$total" ]
