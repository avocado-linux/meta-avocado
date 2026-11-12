#!/usr/bin/env bash
# Host test for stone-provision-ums.sh (the i.MX93 ums profile). Everything that
# touches a disk is a stub (fwup, jq, mount, umount, udevadm, stat, sync), sysfs
# is a fake tree, and the "disks" are regular files under a temp dir, so a stub
# that fails to intercept a write lands in that dir and nowhere else.
#   bash meta-avocado-nxp/stone/avocado-imx/tests/test-stone-provision-ums.sh
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts, so bad runs only when the check failed
set -u
here=$(cd "$(dirname "$0")" && pwd)
script_src=$(readlink -f "${1:-$here/../stone-provision-ums.sh}")
lib_src=$(readlink -f "$here/../../../../meta-avocado-distro/stone/avocado-safe-disk.sh")
vectors=$(readlink -f "$here/../../../../meta-avocado-distro/stone/tests/confirm-vectors.tsv")
# shellcheck source=/dev/null # sibling test helper
. "$here/../../../../meta-avocado-distro/stone/tests/pty-run.sh"
real_stat=$(command -v stat)
w=$(mktemp -d)
trap 'rm -rf "$w"' EXIT
pass=0
fail=0
total=21
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
NVMEPATH=pci0000:00/0000:00:1d.0/0000:01:00.0/nvme/nvme0/nvme0n1
mkdisk() { # name path vendor model
  mkdir -p "$w/sys/devices/$2/$1/device" "$w/sys/class/block"
  ln -s "../../devices/$2/$1" "$w/sys/class/block/$1"
  echo 7864320 >"$w/sys/devices/$2/$1/size"
  printf '%-8s\n' "$3" >"$w/sys/devices/$2/$1/device/vendor"
  printf '%-16s\n' "$4" >"$w/sys/devices/$2/$1/device/model"
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
  cp "$script_src" "$w/run/stone-provision-ums.sh"
  cp "$lib_src" "$w/run/avocado-safe-disk.sh"
  echo '{}' >"$w/manifest.json"
  : >"$w/build/os.aos"
  echo "overlay / overlay rw 0 0" >"$w/st/mounts"
  : >"$w/st/swaps"
  mkdisk sdb "$USBPATH" Linux "UMS disk 0"
  mkpart sdb "$USBPATH" sdb1
  mkdisk sda "$ATAPATH" ATA "Samsung SSD 870"
  mkpart sda "$ATAPATH" sda1
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
exit 0
S
  cat >"$w/bin/jq" <<S
#!/bin/bash
echo os.aos
S
  cat >"$w/bin/mount" <<S
#!/bin/bash
cat "$w/st/mounts"
S
  cat >"$w/bin/umount" <<S
#!/bin/bash
echo "umount \$*" >> "$w/log"
[ -e "$w/st/umount-noop" ] && exit 0
: > "$w/st/mounts"
S
  for t in sync sleep; do
    printf '#!/bin/bash\nexit 0\n' >"$w/bin/$t"
  done
  # Anything else that could write a device is logged, so a stray call shows.
  cat >"$w/bin/dd" <<S
#!/bin/bash
echo "dd \$*" >> "$w/log"
S
  chmod +x "$w/bin/"*
}

envs() {
  echo env PATH="$w/bin:$PATH" AVOCADO_PROVISION_SYSBLOCK="$w/sys/class/block" \
    AVOCADO_SAFE_DISK_MOUNTS="$w/st/mounts" AVOCADO_SAFE_DISK_SWAPS="$w/st/swaps" AVOCADO_SAFE_DISK_DEVDIR="$w/dev" \
    AVOCADO_SAFE_DISK_EUID=0 \
    AVOCADO_STONE_MANIFEST="$w/manifest.json" AVOCADO_STONE_BUILD_DIR="$w/build" AVOCADO_STONE_DATA_DIR="$w"
}
# $1 = stdin (a pipe), remaining args = extra env assignments.
run() {
  local input=$1
  shift
  : >"$w/log"
  # shellcheck disable=SC2046 # envs prints separate words on purpose
  printf '%b' "$input" | $(envs) "$@" bash "$w/run/stone-provision-ums.sh" 2>&1
}
# $1 = keystrokes typed at a terminal, remaining args = env assignments.
run_tty() {
  local input=$1
  shift
  : >"$w/log"
  # shellcheck disable=SC2046
  run_with_tty "$input" $(envs) "$@" bash "$w/run/stone-provision-ums.sh"
}
wrote() { grep -q "^fwup -a" "$w/log" || grep -q "^dd " "$w/log"; }
wrote_to() { grep -q "^fwup -a -u -i $w/build/os.aos -d $1 -t complete" "$w/log"; }
usb() { echo "pci-0000:00:14.0-usb-0:2:1.0-scsi-0:0:0:0" >"$w/st/idpath-$1"; }

# --- the device is required, nothing is searched ------------------------------

setup
usb sdb
out=$(run "")
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "AVOCADO_PROVISION_DEVICE is required"; } \
  && ok "unset device: refused before any write, the disk is not searched for" || bad "unset: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_DEVICE="" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "AVOCADO_PROVISION_DEVICE is required"; } \
  && ok "empty device: refused the same way, FORCE=1 or not" || bad "empty: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_DEVICE="" AVOCADO_PROVISION_DRY_RUN=2)
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "AVOCADO_PROVISION_DRY_RUN=2 is not valid"; } \
  && ok "run-mode variables are validated before the device requirement" || bad "modes first: rc=$rc out=[$out]"

# --- the write ------------------------------------------------------------------

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb" && ! grep -q "^dd " "$w/log"; } \
  && ok "named USB disk: written with fwup -t complete, no dd" || bad "write: rc=$rc out=[$out] log=$(cat "$w/log")"
echo "$out" | grep -q "Bus: " \
  && ok "identity and bus are shown before the write" || bad "identity: out=[$out]"
echo "$out" | grep -q "release the export" \
  && ok "ends telling a Door A operator to release the export" || bad "door a note: out=[$out]"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=1 AVOCADO_PROVISION_FWUP_TASK=upgrade)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "cannot honour AVOCADO_PROVISION_FWUP_TASK=upgrade"; } \
  && ok "task upgrade: refused, only complete is offered" || bad "upgrade: rc=$rc out=[$out]"

# --- guards ---------------------------------------------------------------------

setup
echo "pci-0000:00:17.0-ata-1" >"$w/st/idpath-sda"
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sda" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "not a USB or MMC bus"; } \
  && ok "SATA disk: refused before any write" || bad "sata: rc=$rc out=[$out]"

setup
mkdisk nvme0n1 "$NVMEPATH" "" "Samsung 990"
mkpart nvme0n1 "$NVMEPATH" nvme0n1p1
echo "pci-0000:01:00.0-nvme-1" >"$w/st/idpath-nvme0n1"
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/nvme0n1" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote; } \
  && ok "NVMe disk: refused, never written" || bad "nvme: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb1" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -qi "partition"; } \
  && ok "partition: refused before any write" || bad "partition: rc=$rc out=[$out]"

setup
usb sdb
echo "$w/dev/sdb1 / ext4 rw 0 0" >"$w/st/mounts"
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "running root"; } \
  && ok "the disk holding / is refused even on a USB bus" || bad "root: rc=$rc out=[$out]"

setup
usb sdb
echo "$w/dev/sdb1 /media/x vfat rw 0 0" >"$w/st/mounts"
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -eq 0 ] && grep -q "^umount $w/dev/sdb1" "$w/log" && wrote_to "$w/dev/sdb"; } \
  && ok "a mounted partition is unmounted by the script, then written" || bad "unmount: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
usb sdb
echo "$w/dev/sdb1 /media/x vfat rw 0 0" >"$w/st/mounts"
: >"$w/st/umount-noop"
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "mounted or in use"; } \
  && ok "a partition still mounted after the unmount step is refused" || bad "still mounted: rc=$rc out=[$out]"

# --- confirmation table ---------------------------------------------------------

setup
usb sdb
out=$(run_tty "$w/dev/sdb\n" AVOCADO_PROVISION_DEVICE="$w/dev/sdb")
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb"; } \
  && ok "terminal: retyping the path confirms and writes" || bad "retype ok: rc=$rc out=[$out]"

setup
usb sdb
out=$(run_tty "/dev/other\n" AVOCADO_PROVISION_DEVICE="$w/dev/sdb")
rc=$?
{ [ $rc -ne 0 ] && ! wrote; } \
  && ok "terminal: a wrong retype aborts with no write" || bad "retype wrong: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_FORCE=0)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "no terminal to confirm on"; } \
  && ok "FORCE=0 with no terminal refuses" || bad "force 0: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb")
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb" && echo "$out" | grep -q "no AVOCADO_PROVISION_FORCE signal"; } \
  && ok "FORCE unset with no terminal proceeds with the legacy notice" || bad "legacy: rc=$rc out=[$out]"

[ -s "$vectors" ] \
  && ok "the shared confirmation vectors file is present" || bad "vectors missing: $vectors"

# --- dry run --------------------------------------------------------------------

setup
usb sdb
echo "$w/dev/sdb1 /media/x vfat rw 0 0" >"$w/st/mounts"
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_DRY_RUN=1)
rc=$?
{ [ $rc -eq 0 ] && ! wrote && ! grep -q "^umount" "$w/log" \
  && echo "$out" | grep -q "^dry-run: fwup -a -u -i $w/build/os.aos -d $w/dev/sdb -t complete" \
  && echo "$out" | grep -q "^dry-run: umount" \
  && echo "$out" | grep -q "dry run: nothing was written to $w/dev/sdb"; } \
  && ok "dry run: guards run, the fwup and umount are printed, nothing recorded, exit 0" || bad "dry run: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sdb" AVOCADO_PROVISION_DRY_RUN=1 AVOCADO_PROVISION_FORCE=0)
rc=$?
{ [ $rc -eq 0 ] && ! wrote; } \
  && ok "dry run: never retypes, FORCE=0 does not refuse it" || bad "dry run force0: rc=$rc out=[$out]"

setup
echo "pci-0000:00:17.0-ata-1" >"$w/st/idpath-sda"
out=$(run "" AVOCADO_PROVISION_DEVICE="$w/dev/sda" AVOCADO_PROVISION_DRY_RUN=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "not a USB or MMC bus"; } \
  && ok "dry run: a SATA disk is still refused" || bad "dry run sata: rc=$rc out=[$out]"

echo
echo "passed: $pass  failed: $fail  (checks: $((pass + fail))/$total run)"
[ "$fail" -eq 0 ] && [ $((pass + fail)) -eq "$total" ]
