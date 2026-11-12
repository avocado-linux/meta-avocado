#!/usr/bin/env bash
# Host test for the wrong-disk guards in the stm32mp25-dk stone-provision-sd.sh.
# Everything that touches a disk is a stub (lsblk, blockdev, dd, umount, sync,
# udevadm, stat, build-disk-image.sh), sysfs is a fake tree, and the "disks" are
# regular files under a temp dir, so a stub that fails to intercept a write
# lands in that dir and nowhere else.
#   bash meta-avocado-stm/stone/stm32mp25-dk/tests/test-stone-provision-sd-safe-disk.sh
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts, so bad runs only when the check failed
set -u
here=$(cd "$(dirname "$0")" && pwd)
script_src=$(readlink -f "$here/../stone-provision-sd.sh")
lib_src=$(readlink -f "$here/../../../../meta-avocado-distro/stone/avocado-safe-disk.sh")
pty_src=$(readlink -f "$here/../../../../meta-avocado-distro/stone/tests/pty-run.sh")
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
  echo 1 >"$w/sys/devices/$2/$1/removable"
  : >"$w/dev/$1"
}
mkpart() { # disk path partition
  mkdir -p "$w/sys/devices/$2/$1/$3"
  echo 1 >"$w/sys/devices/$2/$1/$3/partition"
  ln -s "../../devices/$2/$1/$3" "$w/sys/class/block/$3"
  : >"$w/dev/$3"
}

setup() {
  rm -rf "${w:?}/sys" "${w:?}/dev" "${w:?}/st" "${w:?}/bin" "${w:?}/run"
  mkdir -p "$w/dev" "$w/st" "$w/bin" "$w/run"
  cp "$script_src" "$w/run/stone-provision-sd.sh"
  cp "$lib_src" "$w/run/avocado-safe-disk.sh"
  : >"$w/disk.img"
  # The script runs this helper to build the image and uses its stdout as the path.
  printf '#!/bin/bash\necho "%s"\n' "$w/disk.img" >"$w/run/build-disk-image.sh"
  chmod +x "$w/run/build-disk-image.sh"
  echo "overlay / overlay rw 0 0" >"$w/st/mounts"
  : >"$w/st/swaps"
  mkdisk sdb "$USBPATH"
  mkpart sdb "$USBPATH" sdb1
  mkdisk sda "$ATAPATH"
  mkpart sda "$ATAPATH" sda1
  # lsblk lists the removable disks the script would pick from.
  echo "$w/dev/sdb disk 1" >"$w/st/lsblk"
  cat >"$w/bin/lsblk" <<S
#!/bin/bash
cat "$w/st/lsblk"
S
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
  for t in blockdev dd umount sync; do
    cat >"$w/bin/$t" <<S
#!/bin/bash
echo "$t \$*" >> "$w/log"
[ "$t" = blockdev ] && echo 8053063680
exit 0
S
  done
  chmod +x "$w/bin/"*
}

run() {
  local input=$1
  shift
  : >"$w/log"
  printf '%b' "$input" | env PATH="$w/bin:$PATH" AVOCADO_PROVISION_SYSBLOCK="$w/sys/class/block" \
    AVOCADO_SAFE_DISK_MOUNTS="$w/st/mounts" AVOCADO_SAFE_DISK_SWAPS="$w/st/swaps" AVOCADO_SAFE_DISK_DEVDIR="$w/dev" \
    AVOCADO_SAFE_DISK_EUID=0 "$@" bash "$w/run/stone-provision-sd.sh" 2>&1
}
wrote() { grep -q "^dd if=$w/disk.img of=" "$w/log"; }
wrote_to() { grep -q "^dd if=$w/disk.img of=$1 bs=4M" "$w/log"; }
usb() { echo "pci-0000:00:14.0-usb-0:2:1.0-scsi-0:0:0:0" >"$w/st/idpath-$1"; }
sata() { echo "pci-0000:00:17.0-ata-1" >"$w/st/idpath-$1"; }
# shellcheck source=/dev/null # sibling test helper, absent from a standalone lint
. "$pty_src"
# trun <typed> [NAME=value ...]: run the script with the keystrokes typed on a real terminal.
trun() {
  local typed=$1
  shift
  : >"$w/log"
  PATH="$w/bin:$PATH" AVOCADO_PROVISION_SYSBLOCK="$w/sys/class/block" \
    AVOCADO_SAFE_DISK_MOUNTS="$w/st/mounts" AVOCADO_SAFE_DISK_SWAPS="$w/st/swaps" AVOCADO_SAFE_DISK_DEVDIR="$w/dev" \
    AVOCADO_SAFE_DISK_EUID=0 \
    run_with_tty "$typed" env "$@" bash "$w/run/stone-provision-sd.sh"
}

setup
usb sdb
out=$(trun "$w/dev/sdb\\n" AVOCADO_PROVISION_FORCE=0)
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb" && echo "$out" | grep -q "SD card written"; } \
  && ok "a whole USB disk is written after the path is retyped on a terminal" || bad "pass: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
usb sdb
out=$(trun 'y\n' AVOCADO_PROVISION_FORCE=0)
rc=$?
{ [ $rc -ne 0 ] && ! wrote; } \
  && ok "y no longer confirms: the path must be typed" || bad "y: rc=$rc out=[$out]"

setup
usb sdb
out=$(trun "" AVOCADO_PROVISION_FORCE=0)
rc=$?
{ [ $rc -ne 0 ] && ! wrote; } \
  && ok "end of input at the prompt aborts" || bad "eof: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb" && echo "$out" | grep -q "Model:"; } \
  && ok "AVOCADO_PROVISION_FORCE=1 writes without asking and still shows the identity" || bad "force: rc=$rc out=[$out]"

setup
sata sda
echo "$w/dev/sda disk 1" >"$w/st/lsblk"
out=$(run "$w/dev/sda\n" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "not a USB or MMC bus"; } \
  && ok "a SATA disk the kernel flags removable is refused, even with FORCE" || bad "sata removable: rc=$rc out=[$out]"

setup
usb sdb
echo "$w/dev/sdb1 / ext4 rw 0 0" >"$w/st/mounts"
out=$(run "" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "running root"; } \
  && ok "the disk holding / is refused" || bad "root: rc=$rc out=[$out]"

setup
usb sdb
echo "$w/dev/sdb1 /media/stick vfat rw 0 0" >"$w/st/mounts"
out=$(run "" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "mounted or in use"; } \
  && ok "a partition still mounted after the unmount step is refused" || bad "mounted: rc=$rc out=[$out]"

# --- run modes, device selection and the retype (provision-run-modes,
# --- provision-disk-guards, provision-confirmation-policy)

setup
usb sdb
echo "$w/dev/sda disk 1" >"$w/st/lsblk"
echo "$w/dev/sdb disk 1" >>"$w/st/lsblk"
out=$(run "$w/dev/sdb\n" AVOCADO_SD_DEVICE="$w/dev/sdb")
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb"; } \
  && ok "AVOCADO_SD_DEVICE alone selects the disk (two removable disks listed)" || bad "sd_device alone: rc=$rc out=[$out]"

setup
usb sdb
echo "$w/dev/sda disk 1" >"$w/st/lsblk"
echo "$w/dev/sdb disk 1" >>"$w/st/lsblk"
out=$(run "$w/dev/sdb\n" AVOCADO_PROVISION_DEVICE="$w/dev/sdb")
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb"; } \
  && ok "AVOCADO_PROVISION_DEVICE alone selects the disk" || bad "provision_device alone: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "$w/dev/sdb\n" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_SD_DEVICE="$w/dev/sda")
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "differ"; } \
  && ok "conflicting device variables are refused" || bad "conflict: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "y\n" AVOCADO_SD_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=0)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "no terminal to confirm on"; } \
  && ok "a named device still needs the retype: a piped y does not confirm" || bad "named y: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "" AVOCADO_SD_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb"; } \
  && ok "a named device with FORCE=1 writes without asking" || bad "named force: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_DRY_RUN=1)
rc=$?
{ [ $rc -eq 0 ] && ! wrote && ! grep -q '^dd ' "$w/log" && echo "$out" | grep -q "^dry-run: dd if=" \
  && echo "$out" | grep -q "dry run: nothing was written to $w/dev/sdb"; } \
  && ok "a dry run prints the write, records no dd, asks no retype, exits 0" || bad "dry run: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
usb sdb
echo "$w/dev/sdb1 / ext4 rw 0 0" >"$w/st/mounts"
out=$(run "" AVOCADO_PROVISION_DRY_RUN=1)
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "running root"; } \
  && ok "a dry run still runs the guards" || bad "dry run guards: rc=$rc out=[$out]"

setup
usb sdb
echo "$w/dev/sdb1 /media/stick vfat rw 0 0" >"$w/st/mounts"
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_DRY_RUN=1)
rc=$?
{ [ $rc -eq 0 ] && ! wrote && ! grep -q "^umount" "$w/log" && echo "$out" | grep -q "dry-run: umount" \
  && echo "$out" | grep -q "a real run would unmount it first"; } \
  && ok "dry run: a mounted partition is reported, not unmounted" || bad "dry run mounted: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
usb sdb
echo "$w/dev/sdb1 /media/stick vfat rw 0 0" >"$w/st/hostmounts"
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_DRY_RUN=1 AVOCADO_PROVISION_HOST_MOUNTS="$w/st/hostmounts")
rc=$?
{ [ $rc -ne 0 ] && ! wrote && ! grep -q "^umount" "$w/log" && echo "$out" | grep -q "mounted or in use (hostmounts)"; } \
  && ok "dry run: a partition mounted on the host is refused, not unmounted" || bad "dry run host mount: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
usb sdb
out=$(run "$w/dev/sdb\n" AVOCADO_PROVISION_DRY_RUN=2)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "not valid"; } \
  && ok "an invalid AVOCADO_PROVISION_DRY_RUN value is refused" || bad "bad dry run: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "$w/dev/sdb\n" AVOCADO_PROVISION_FWUP_TASK=upgrade)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "cannot honour"; } \
  && ok "a task other than complete is refused" || bad "task upgrade: rc=$rc out=[$out]"

# A real terminal on stdin: the retype is read from it, and y does not confirm.
if command -v script >/dev/null 2>&1; then
  # shellcheck source=/dev/null # sibling test helper, absent from a standalone lint
  . "$pty_src"
  tty_run() { # input; env goes through the environment of this shell
    : >"$w/log"
    PATH="$w/bin:$PATH" AVOCADO_PROVISION_SYSBLOCK="$w/sys/class/block" \
      AVOCADO_SAFE_DISK_MOUNTS="$w/st/mounts" AVOCADO_SAFE_DISK_SWAPS="$w/st/swaps" AVOCADO_SAFE_DISK_DEVDIR="$w/dev" \
      AVOCADO_SAFE_DISK_EUID=0 AVOCADO_SD_DEVICE="$w/dev/sdb" \
      run_with_tty "$1" bash "$w/run/stone-provision-sd.sh"
  }
  setup
  usb sdb
  out=$(tty_run 'y\n')
  rc=$?
  { [ $rc -ne 0 ] && ! wrote; } \
    && ok "on a terminal, y does not confirm a named device" || bad "tty y: rc=$rc out=[$out]"
  setup
  usb sdb
  out=$(tty_run "$w/dev/sdb\\n")
  rc=$?
  { [ $rc -eq 0 ] && wrote_to "$w/dev/sdb"; } \
    && ok "on a terminal, the retyped path confirms a named device" || bad "tty path: rc=$rc out=[$out]"
else
  bad "script(1) missing: terminal checks not run"
  bad "script(1) missing: terminal checks not run"
fi

echo
echo "passed: $pass  failed: $fail  (checks: $((pass + fail))/20 run)"
[ "$fail" -eq 0 ] && [ $((pass + fail)) -eq 20 ]
