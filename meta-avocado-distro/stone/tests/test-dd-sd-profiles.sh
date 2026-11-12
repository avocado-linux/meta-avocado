#!/usr/bin/env bash
# Shared host test for the dd-family sd profiles: scripts that build a whole
# disk image with build-disk-image.sh and dd it to an SD card through the
# safe-disk library. The script under test is the first argument:
#
#   bash meta-avocado-distro/stone/tests/test-dd-sd-profiles.sh \
#     meta-avocado-alif/stone/alif-e8-devkit/stone-provision-sd.sh
#
# Only what every such profile shares is asserted here: device selection, the
# disk guards, the confirmation policy and the run modes. Board banners and
# boot instructions are not.
#
# Everything that touches a disk is a stub (lsblk, blockdev, dd, umount, sync,
# udevadm, stat, build-disk-image.sh), sysfs is a fake tree, and the "disks" are
# regular files under a temp dir, so a stub that fails to intercept a write
# lands in that dir and nowhere else. lsblk reports every fake disk with the
# kernel removable flag set, so a script that still selects by that flag picks
# a disk the bus check would refuse.
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts, so bad runs only when the check failed
set -u
if [ $# -ne 1 ] || [ ! -f "$1" ]; then
  echo "usage: $0 <path to a dd-family stone-provision-sd.sh>" >&2
  exit 2
fi
script_src=$(readlink -f "$1")
here=$(cd "$(dirname "$0")" && pwd)
lib_src=$(readlink -f "$here/../avocado-safe-disk.sh")
pty_src=$(readlink -f "$here/pty-run.sh")
real_stat=$(command -v stat)
w=$(mktemp -d)
trap 'rm -rf "$w"' EXIT
pass=0
fail=0
expected=20
ok() {
  echo "  ok   - $1"
  pass=$((pass + 1))
}
bad() {
  echo "  FAIL - $1"
  fail=$((fail + 1))
}

echo "script under test: $script_src"

USBPATH=pci0000:00/0000:00:14.0/usb1/1-2/1-2:1.0/host6/target6:0:0/6:0:0:0/block
USB2PATH=pci0000:00/0000:00:14.0/usb1/1-3/1-3:1.0/host7/target7:0:0/7:0:0:0/block
ATAPATH=pci0000:00/0000:00:17.0/ata1/host0/target0:0:0/0:0:0:0/block
NVMEPATH=pci0000:00/0000:00:1d.0/0000:01:00.0/nvme/nvme0
mkdisk() { # name path
  mkdir -p "$w/sys/devices/$2/$1/device" "$w/sys/class/block"
  ln -s "../../devices/$2/$1" "$w/sys/class/block/$1"
  echo 7864320 >"$w/sys/devices/$2/$1/size"
  echo 1 >"$w/sys/devices/$2/$1/removable"
  : >"$w/dev/$1"
  echo "$w/dev/$1 disk 1" >>"$w/st/lsblk"
}
mkpart() { # disk path partition
  mkdir -p "$w/sys/devices/$2/$1/$3"
  echo 1 >"$w/sys/devices/$2/$1/$3/partition"
  ln -s "../../devices/$2/$1/$3" "$w/sys/class/block/$3"
  : >"$w/dev/$3"
}
# udev ID_PATH as the udevadm stub reports it for a disk.
usb() { echo "pci-0000:00:14.0-usb-0:2:1.0-scsi-0:0:0:0" >"$w/st/idpath-$1"; }
sata() { echo "pci-0000:00:17.0-ata-1" >"$w/st/idpath-$1"; }
nvme() { echo "pci-0000:01:00.0-nvme-1" >"$w/st/idpath-$1"; }

# A fresh tree with no disks. Callers add the disks a case needs.
setup() {
  rm -rf "${w:?}/sys" "${w:?}/dev" "${w:?}/st" "${w:?}/bin" "${w:?}/run"
  mkdir -p "$w/dev" "$w/st" "$w/bin" "$w/run" "$w/sys/class/block"
  : >"$w/st/lsblk"
  cp "$script_src" "$w/run/stone-provision-sd.sh"
  cp "$lib_src" "$w/run/avocado-safe-disk.sh"
  : >"$w/disk.img"
  # The script runs this helper to build the image and uses its stdout as the path.
  printf '#!/bin/bash\necho "%s"\n' "$w/disk.img" >"$w/run/build-disk-image.sh"
  chmod +x "$w/run/build-disk-image.sh"
  echo "overlay / overlay rw 0 0" >"$w/st/mounts"
  : >"$w/st/swaps"
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

# The common USB card reader at sdb, with a SATA disk at sda that the kernel
# also flags removable.
reader_and_sata() {
  mkdisk sdb "$USBPATH"
  mkpart sdb "$USBPATH" sdb1
  usb sdb
  mkdisk sda "$ATAPATH"
  mkpart sda "$ATAPATH" sda1
  sata sda
}
reader_only() {
  mkdisk sdb "$USBPATH"
  mkpart sdb "$USBPATH" sdb1
  usb sdb
}

envs() {
  printf '%s\n' PATH="$w/bin:$PATH" AVOCADO_PROVISION_SYSBLOCK="$w/sys/class/block" \
    AVOCADO_SAFE_DISK_MOUNTS="$w/st/mounts" AVOCADO_SAFE_DISK_SWAPS="$w/st/swaps" \
    AVOCADO_SAFE_DISK_DEVDIR="$w/dev" AVOCADO_SAFE_DISK_EUID=0 \
    AVOCADO_SAFE_DISK_CONTAINER_MARKERS="$w/no-such-marker"
}

# Standard input is a pipe carrying $1 (a printf format).
run() {
  local input=$1 base
  shift
  : >"$w/log"
  mapfile -t base < <(envs)
  # The caller's environment must not leak a device or force value in.
  printf '%b' "$input" | env -u AVOCADO_PROVISION_DEVICE -u AVOCADO_SD_DEVICE -u AVOCADO_PROVISION_FORCE \
    -u AVOCADO_PROVISION_DRY_RUN -u AVOCADO_PROVISION_FWUP_TASK -u AVOCADO_USB_PASSTHROUGH \
    "${base[@]}" "$@" bash "$w/run/stone-provision-sd.sh" 2>&1
}

wrote() { grep -q "^dd if=$w/disk.img of=" "$w/log"; }
wrote_to() { grep -q "^dd if=$w/disk.img of=$1 bs=4M" "$w/log"; }

# --- named device: guards and confirmation (provision-disk-guards,
# --- provision-confirmation-policy)

setup
reader_and_sata
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb" && echo "$out" | grep -q "Model:"; } \
  && ok "a named USB disk with FORCE=1 is written and its identity shown" || bad "named force: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
reader_and_sata
out=$(run "y\ny\ny\n" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=0)
rc=$?
{ [ $rc -ne 0 ] && ! wrote; } \
  && ok "a named device with FORCE=0 and a piped y refuses" || bad "named piped y: rc=$rc out=[$out]"

setup
reader_and_sata
out=$(run "y\n" AVOCADO_PROVISION_DEVICE="$w/dev/sdb")
rc=$?
{ [ $rc -ne 0 ] && ! wrote; } \
  && ok "a named device still needs the retype: a piped y does not confirm" || bad "named y unset force: rc=$rc out=[$out]"

setup
mkdisk nvme0n1 "$NVMEPATH"
nvme nvme0n1
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/nvme0n1" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "not a USB or MMC bus"; } \
  && ok "a named NVMe disk is refused, even with FORCE=1" || bad "nvme: rc=$rc out=[$out]"

setup
reader_and_sata
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sda" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "not a USB or MMC bus"; } \
  && ok "a SATA disk the kernel flags removable is refused, even with FORCE=1" || bad "sata removable: rc=$rc out=[$out]"

setup
reader_and_sata
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb1" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "pass the whole disk"; } \
  && ok "a partition is refused: only a whole disk is written" || bad "partition: rc=$rc out=[$out]"

setup
reader_and_sata
echo "$w/dev/sdb1 / ext4 rw 0 0" >"$w/st/mounts"
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "running root"; } \
  && ok "the disk holding / is refused" || bad "root: rc=$rc out=[$out]"

setup
reader_and_sata
echo "$w/dev/sdb1 /media/card vfat rw 0 0" >"$w/st/mounts"
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "mounted or in use"; } \
  && ok "a partition still mounted after the unmount step is refused" || bad "mounted: rc=$rc out=[$out]"

setup
reader_and_sata
out=$(run "" AVOCADO_SD_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb"; } \
  && ok "AVOCADO_SD_DEVICE is an alias for AVOCADO_PROVISION_DEVICE" || bad "alias: rc=$rc out=[$out]"

setup
reader_and_sata
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_SD_DEVICE="$w/dev/sda" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "differ"; } \
  && ok "conflicting device variables are refused" || bad "conflict: rc=$rc out=[$out]"

# --- no device named: selection (provision-disk-guards, provision-confirmation-policy)

# The card reader is the only disk, so it is the lone candidate whichever way a
# script enumerates.
setup
reader_only
out=$(run "" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && ! grep -q '^umount ' "$w/log"; } \
  && ok "a lone candidate with no device named, no terminal and FORCE=1 refuses and records no dd" \
  || bad "lone no tty force: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
reader_only
out=$(run "y\n")
rc=$?
{ [ $rc -ne 0 ] && ! wrote; } \
  && ok "a piped y cannot choose the lone candidate" || bad "lone piped y: rc=$rc out=[$out]"

# --- run modes (provision-run-modes)

setup
reader_and_sata
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_DRY_RUN=1)
rc=$?
{ [ $rc -eq 0 ] && ! wrote && ! grep -q '^dd \|^umount ' "$w/log" && echo "$out" | grep -q "^dry-run: dd if=" \
  && echo "$out" | grep -q "dry run: nothing was written to $w/dev/sdb"; } \
  && ok "a dry run prints the write, records no dd or umount, asks no retype, exits 0" || bad "dry run: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
mkdisk nvme0n1 "$NVMEPATH"
nvme nvme0n1
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/nvme0n1" AVOCADO_PROVISION_DRY_RUN=1)
rc=$?
{ [ $rc -ne 0 ] && ! echo "$out" | grep -q "dry run: nothing was written"; } \
  && ok "a dry run still runs the guards" || bad "dry run guards: rc=$rc out=[$out]"

setup
reader_and_sata
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_DRY_RUN=true)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && [ ! -s "$w/log" ] && echo "$out" | grep -q "not valid"; } \
  && ok "an invalid AVOCADO_PROVISION_DRY_RUN value is refused before any work" || bad "bad dry run: rc=$rc out=[$out]"

setup
reader_and_sata
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=1 AVOCADO_PROVISION_FWUP_TASK=upgrade)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "upgrade"; } \
  && ok "a task other than complete is refused" || bad "task upgrade: rc=$rc out=[$out]"

# --- a real terminal on stdin

if command -v script >/dev/null 2>&1; then
  # shellcheck source=/dev/null # sibling test helper, absent from a standalone lint
  . "$pty_src"
  tty_run() { # input, then VAR=value assignments
    local input=$1 base
    shift
    : >"$w/log"
    mapfile -t base < <(envs)
    (
      unset AVOCADO_PROVISION_DEVICE AVOCADO_SD_DEVICE AVOCADO_PROVISION_FORCE \
        AVOCADO_PROVISION_DRY_RUN AVOCADO_PROVISION_FWUP_TASK AVOCADO_USB_PASSTHROUGH
      # shellcheck disable=SC2163 # the arguments are VAR=value assignments
      export "${base[@]}" "$@"
      run_with_tty "$input" bash "$w/run/stone-provision-sd.sh"
    )
  }

  setup
  reader_and_sata
  out=$(tty_run "$w/dev/sdb\\n")
  rc=$?
  { [ $rc -eq 0 ] && wrote_to "$w/dev/sdb" && ! grep -q "of=$w/dev/sda " "$w/log"; } \
    && ok "a lone candidate on a terminal is picked after the bus check" || bad "tty lone: rc=$rc out=[$out] log=$(cat "$w/log")"

  # A SATA disk flagged removable is the only disk: a script selecting by the
  # flag would pick it, so both a y and the retyped path are offered.
  setup
  mkdisk sda "$ATAPATH"
  sata sda
  out=$(tty_run "y\\n$w/dev/sda\\n")
  rc=$?
  { [ $rc -ne 0 ] && ! wrote; } \
    && ok "the removable flag never selects a disk: no USB or MMC candidate refuses" || bad "tty removable only: rc=$rc out=[$out]"

  setup
  reader_and_sata
  mkdisk sdc "$USB2PATH"
  usb sdc
  out=$(tty_run "$w/dev/sdb\\n")
  rc=$?
  { [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "$w/dev/sdc"; } \
    && ok "two candidates are listed and refused, even on a terminal" || bad "tty two: rc=$rc out=[$out]"

  setup
  reader_and_sata
  out=$(tty_run 'y\n' AVOCADO_PROVISION_DEVICE="$w/dev/sdb")
  rc=$?
  { [ $rc -ne 0 ] && ! wrote; } \
    && ok "on a terminal, y does not confirm a named device" || bad "tty y: rc=$rc out=[$out]"
else
  bad "script(1) missing: terminal checks not run"
fi

echo
echo "passed: $pass  failed: $fail  (checks: $((pass + fail))/$expected run)"
[ "$fail" -eq 0 ] && [ $((pass + fail)) -eq "$expected" ]
