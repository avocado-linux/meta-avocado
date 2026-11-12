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
    "$@" bash "$w/run/stone-provision-sd.sh" 2>&1
}
wrote() { grep -q "^dd if=$w/disk.img of=" "$w/log"; }
wrote_to() { grep -q "^dd if=$w/disk.img of=$1 bs=4M" "$w/log"; }
usb() { echo "pci-0000:00:14.0-usb-0:2:1.0-scsi-0:0:0:0" >"$w/st/idpath-$1"; }
sata() { echo "pci-0000:00:17.0-ata-1" >"$w/st/idpath-$1"; }

setup
usb sdb
out=$(run "$w/dev/sdb\n")
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb" && echo "$out" | grep -q "SD card written"; } \
  && ok "a whole USB disk is written after the path is retyped" || bad "pass: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
usb sdb
out=$(run "y\n")
rc=$?
{ [ $rc -ne 0 ] && ! wrote; } \
  && ok "y no longer confirms: the path must be typed" || bad "y: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "")
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

echo
echo "passed: $pass  failed: $fail  (checks: $((pass + fail))/7 run)"
[ "$fail" -eq 0 ] && [ $((pass + fail)) -eq 7 ]
