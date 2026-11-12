#!/usr/bin/env bash
# Host test for the wrong-disk guards in stone-provision-usb.sh. Everything that
# touches hardware is a stub (rpiboot, fwup, dd, mount, umount, udevadm, stat,
# sudo), sysfs is a fake tree, and the "disks" are regular files under a temp
# dir, so a stub that fails to intercept a write lands in that dir and nowhere
# else. rpiboot's stub is what makes the gadget disk appear, as the real one does.
#   bash meta-avocado-raspberrypi/stone/rpi/tests/test-stone-provision-usb-safe-disk.sh
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts, so bad runs only when the check failed
set -u
here=$(cd "$(dirname "$0")" && pwd)
script_src=$(readlink -f "$here/../stone-provision-usb.sh")
lib_src=$(readlink -f "$here/../../../../meta-avocado-distro/stone/avocado-safe-disk.sh")
# shellcheck source=/dev/null
. "$here/../../../../meta-avocado-distro/stone/tests/pty-run.sh"
real_stat=$(command -v stat)
w=$(mktemp -d)
trap 'rm -rf "$w"' EXIT
pass=0
fail=0
total=20
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
USBDEV=pci0000:00/0000:00:14.0/usb1/1-2
mkdisk() { # name path
  mkdir -p "$w/sys/devices/$2/$1/device" "$w/sys/class/block"
  ln -s "../../devices/$2/$1" "$w/sys/class/block/$1"
  echo 7864320 >"$w/sys/devices/$2/$1/size"
  echo "Linux" >"$w/sys/devices/$2/$1/device/vendor"
  echo "Gadget" >"$w/sys/devices/$2/$1/device/model"
  : >"$w/dev/$1"
}
mkpart() { # disk path partition
  mkdir -p "$w/sys/devices/$2/$1/$3"
  echo 1 >"$w/sys/devices/$2/$1/$3/partition"
  ln -s "../../devices/$2/$1/$3" "$w/sys/class/block/$3"
  : >"$w/dev/$3"
}

setup() {
  rm -rf "${w:?}/sys" "${w:?}/dev" "${w:?}/st" "${w:?}/bin" "${w:?}/build" "${w:?}/run" "${w:?}/sysroot"
  mkdir -p "$w/dev" "$w/st" "$w/bin" "$w/build" "$w/run" "$w/sys/block" "$w/sys/bus/usb/devices/1-1" \
    "$w/sysroot/usr/bin" "$w/sysroot/usr/share/rpiboot/mass-storage-gadget64"
  cp "$script_src" "$w/run/stone-provision-usb.sh"
  cp "$lib_src" "$w/run/avocado-safe-disk.sh"
  echo '{}' >"$w/manifest.json"
  : >"$w/build/os.aos"
  echo "overlay / overlay rw 0 0" >"$w/st/mounts"
  : >"$w/st/swaps"
  # The Pi in boot mode, waiting for rpiboot.
  echo 0a5c >"$w/sys/bus/usb/devices/1-1/idVendor"
  echo 2711 >"$w/sys/bus/usb/devices/1-1/idProduct"
  # A disk that is already there, before rpiboot runs.
  mkdisk sda "$ATAPATH"
  mkpart sda "$ATAPATH" sda1
  ln -s ../class/block/sda "$w/sys/block/sda"
  # The gadget disk, which rpiboot's stub links into /sys/block.
  mkdisk sdb "$USBPATH"
  mkpart sdb "$USBPATH" sdb1
  mkdir -p "$w/sys/devices/$USBDEV"
  echo 0a5c >"$w/sys/devices/$USBDEV/idVendor"
  echo 0104 >"$w/sys/devices/$USBDEV/idProduct"
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
  cat >"$w/sysroot/usr/bin/rpiboot" <<S
#!/bin/bash
echo "rpiboot \$*" >> "$w/log"
[ -e "$w/sys/block/sdb" ] || ln -s ../class/block/sdb "$w/sys/block/sdb"
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
case "\$*" in
  *rootdisk.out*) echo os.aos ;;
  *devpath*) echo /dev/mmcblk0 ;;
  *offset_unit*) echo mebibytes ;;
  *size_unit*) echo kibibytes ;;
  *.offset*) echo 1 ;;
  *.size*) echo 1 ;;
esac
S
  cat >"$w/bin/bc" <<S
#!/bin/bash
echo 3.7
S
  cat >"$w/bin/mount" <<S
#!/bin/bash
cat "$w/st/mounts"
S
  # umount drops the lines naming its arguments unless st/umount-noop exists.
  cat >"$w/bin/umount" <<S
#!/bin/bash
echo "umount \$*" >> "$w/log"
[ -e "$w/st/umount-noop" ] && exit 0
: > "$w/st/mounts"
S
  cat >"$w/bin/dd" <<S
#!/bin/bash
echo "dd \$*" >> "$w/log"
exit 0
S
  cat >"$w/bin/sleep" <<S
#!/bin/bash
exit 0
S
  cat >"$w/bin/sudo" <<S
#!/bin/bash
echo "sudo \$*" >> "$w/log"
exec "\$@"
S
  chmod +x "$w/bin/"* "$w/sysroot/usr/bin/"*
}

# The environment every run gets; extra assignments from the case follow it.
base_env() {
  printf '%s\n' "PATH=$w/bin:$w/sysroot/usr/bin:$PATH" "SYSFS=$w/sys" "AVOCADO_PROVISION_SYSBLOCK=$w/sys/class/block" \
    "AVOCADO_SAFE_DISK_MOUNTS=$w/st/mounts" "AVOCADO_SAFE_DISK_SWAPS=$w/st/swaps" "AVOCADO_SAFE_DISK_DEVDIR=$w/dev" \
    "AVOCADO_SAFE_DISK_EUID=0" "AVOCADO_STONE_MANIFEST=$w/manifest.json" "AVOCADO_STONE_BUILD_DIR=$w/build" \
    "AVOCADO_STONE_DATA_DIR=$w"
}

# $1 = stdin (piped, so not a terminal), remaining args = extra env assignments.
run() {
  local input=$1 base
  shift
  mapfile -t base < <(base_env)
  : >"$w/log"
  printf '%b' "$input" | env "${base[@]}" "$@" bash "$w/run/stone-provision-usb.sh" 2>&1
}
# $1 = keystrokes, remaining args = extra env assignments; stdin is a terminal.
run_tty() {
  local input=$1 base
  shift
  mapfile -t base < <(base_env)
  : >"$w/log"
  run_with_tty "$input" env "${base[@]}" "$@" bash "$w/run/stone-provision-usb.sh" 2>&1
}
wrote() { grep -q "^fwup -a -u " "$w/log"; }
wrote_to() { grep -q "^fwup -a -u --no-verify-writes -i $w/build/os.aos -d $1 -t ${2:-complete}\$" "$w/log"; }
cleared() { grep -q "^dd .*of=$1 " "$w/log"; }
started() { grep -q "^rpiboot " "$w/log" || grep -q "^fwup " "$w/log"; }
usb() { echo "pci-0000:00:14.0-usb-0:2:1.0-scsi-0:0:0:0" >"$w/st/idpath-$1"; }
sata() { echo "pci-0000:00:17.0-ata-1" >"$w/st/idpath-$1"; }

# --- run modes: refused before rpiboot or fwup starts -------------------------

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_DRY_RUN=1 AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! started && echo "$out" | grep -q "profile usb does not support a dry run"; } \
  && ok "DRY_RUN=1 is refused naming the usb profile, with rpiboot and fwup never started" || bad "dry run: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_DRY_RUN=0 AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! started && echo "$out" | grep -q "not valid"; } \
  && ok "DRY_RUN=0 is refused before rpiboot" || bad "dry run 0: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_FWUP_TASK=bogus AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! started && echo "$out" | grep -q "not valid"; } \
  && ok "an unknown FWUP_TASK is refused before rpiboot" || bad "bogus task: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_FWUP_TASK=upgrade AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb" upgrade; } \
  && ok "FWUP_TASK=upgrade reaches fwup as -t upgrade" || bad "upgrade task: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
usb sdb
rm "$w/build/os.aos"
out=$(run "" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! started && echo "$out" | grep -q "Archive file not found"; } \
  && ok "a missing payload is refused before rpiboot, so before any target is shown" || bad "payload: rc=$rc out=[$out]"

# --- guards on the disk rpiboot exposes --------------------------------------

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb" && cleared "$w/dev/sdb"; } \
  && ok "a whole USB gadget disk is written with FORCE=1 and no prompt" || bad "force pass: rc=$rc out=[$out] log=$(cat "$w/log")"
echo "$out" | grep -q "Bus: " \
  && ok "the model, size and bus are shown before the write" || bad "identity: out=[$out]"

setup
sata sdb
out=$(run "" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && ! cleared "$w/dev/sdb" && echo "$out" | grep -q "not a USB or MMC bus"; } \
  && ok "a disk on a SATA bus is refused even with FORCE, before the uboot-env clear" || bad "sata: rc=$rc out=[$out]"

setup
usb sdb
echo "$w/dev/sdb1,8053063680" >"$w/st/fwup-devices"
out=$(run "" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -qi "partition"; } \
  && ok "a partition is refused before any write" || bad "partition: rc=$rc out=[$out]"

setup
usb sdb
echo "$w/dev/sdb1 / ext4 rw 0 0" >"$w/st/mounts"
out=$(run "" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "running root"; } \
  && ok "the disk holding / is refused even on a USB bus" || bad "root: rc=$rc out=[$out]"

setup
usb sdb
echo "$w/dev/sdb1 /media/stick vfat rw 0 0" >"$w/st/mounts"
out=$(run "" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -eq 0 ] && grep -q "^umount $w/dev/sdb" "$w/log" && wrote_to "$w/dev/sdb"; } \
  && ok "a mounted partition is unmounted by the script and the write proceeds" || bad "unmount: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
usb sdb
echo "$w/dev/sdb1 /media/stick vfat rw 0 0" >"$w/st/mounts"
: >"$w/st/umount-noop"
out=$(run "" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && ! cleared "$w/dev/sdb" && echo "$out" | grep -q "mounted or in use"; } \
  && ok "a partition still mounted after the unmount step is refused before any write" || bad "still mounted: rc=$rc out=[$out]"

setup
usb sdb
echo "$w/dev/sdb1 /mnt/host ext4 rw 0 0" >"$w/st/host-mounts"
out=$(run "" AVOCADO_PROVISION_FORCE=1 AVOCADO_PROVISION_HOST_MOUNTS="$w/st/host-mounts")
rc=$?
{ [ $rc -ne 0 ] && ! wrote && ! cleared "$w/dev/sdb" && echo "$out" | grep -q "mounted or in use (host-mounts)"; } \
  && ok "a host mount of the disk, from the exported table, is refused" || bad "host mount: rc=$rc out=[$out]"

setup
usb sdb
echo "$w/dev/sdb,8053063680" >"$w/st/fwup-devices"
echo 1234 >"$w/sys/devices/$USBDEV/idProduct"
out=$(run "" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "not the rpiboot mass-storage gadget"; } \
  && ok "an unattended run refuses a disk that is not the rpiboot gadget" || bad "non-gadget: rc=$rc out=[$out]"

# --- confirmation -------------------------------------------------------------

setup
usb sdb
out=$(run_tty "$w/dev/sdb\\n")
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb"; } \
  && ok "retyping the device path on a terminal confirms and writes" || bad "retype pass: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
usb sdb
out=$(run_tty 'y\n')
rc=$?
{ [ $rc -ne 0 ] && ! wrote && ! cleared "$w/dev/sdb"; } \
  && ok "answering y no longer confirms; nothing is cleared or written" || bad "y answer: rc=$rc out=[$out]"

setup
usb sdb
out=$(run_tty "")
rc=$?
{ [ $rc -ne 0 ] && ! wrote && ! cleared "$w/dev/sdb"; } \
  && ok "end of input at the prompt aborts without FORCE" || bad "eof: rc=$rc out=[$out]"

setup
usb sdb
out=$(run_tty "$w/dev/sdb\n")
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb"; } \
  && ok "on a terminal, retyping the device path confirms and writes" || bad "tty retype: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
usb sdb
out=$(run_tty "y\n")
rc=$?
{ [ $rc -ne 0 ] && ! wrote; } \
  && ok "on a terminal, a wrong retype aborts" || bad "tty wrong: rc=$rc out=[$out]"

# --- privilege ----------------------------------------------------------------

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_FORCE=1 AVOCADO_SAFE_DISK_EUID=1000)
rc=$?
{ [ $rc -eq 0 ] && grep -q "^sudo .*/fwup -a -u " "$w/log" && grep -q "^sudo .*/dd " "$w/log" && wrote_to "$w/dev/sdb"; } \
  && ok "as a non-root user the clear and the write both go through sudo" || bad "sudo: rc=$rc out=[$out] log=$(cat "$w/log")"

echo
echo "passed: $pass  failed: $fail  (checks: $((pass + fail))/$total run)"
[ "$fail" -eq 0 ] && [ $((pass + fail)) -eq $total ]
