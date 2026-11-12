#!/usr/bin/env bash
# Host test for the wrong-disk guards in stone-provision-ums.sh (the sd-usb
# profile). Everything that touches hardware is a stub (dd, sync, mount, umount,
# udevadm, stat, sudo, sleep, build-disk-image.sh), sysfs is a fake tree holding
# the disk U-Boot's `ums 0 mmc 1` exposes (vendor "Linux", model "UMS disk 0"),
# and the "disks" are regular files under a temp dir, so a stub that fails to
# intercept a write lands in that dir and nowhere else.
#   bash meta-avocado-rockchip/stone/nanopi-r5s/tests/test-stone-provision-ums.sh
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts, so bad runs only when the check failed
set -u
here=$(cd "$(dirname "$0")" && pwd)
script_src=$(readlink -f "$here/../stone-provision-ums.sh")
lib_src=$(readlink -f "$here/../../../../meta-avocado-distro/stone/avocado-safe-disk.sh")
# shellcheck source=/dev/null
. "$here/../../../../meta-avocado-distro/stone/tests/pty-run.sh"
real_stat=$(command -v stat)
w=$(mktemp -d)
trap 'rm -rf "$w"' EXIT
pass=0
fail=0
total=24
ok() {
  echo "  ok   - $1"
  pass=$((pass + 1))
}
bad() {
  echo "  FAIL - $1"
  fail=$((fail + 1))
}

USBPATH=platform/fcd00000.usb/xhci-hcd.0.auto/usb2/2-1/2-1:1.0/host2/target2:0:0/2:0:0:0/block
ATAPATH=pci0000:00/0000:00:17.0/ata1/host0/target0:0:0/0:0:0:0/block
mkdisk() { # name path vendor model
  mkdir -p "$w/sys/devices/$2/$1/device" "$w/sys/class/block" "$w/sys/block"
  ln -s "../../devices/$2/$1" "$w/sys/class/block/$1"
  ln -s "../class/block/$1" "$w/sys/block/$1"
  echo 7864320 >"$w/sys/devices/$2/$1/size"
  # SCSI pads both fields with spaces, as the kernel shows them.
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

# $1 = path the UMS disk sits on (default the USB host); "none" leaves it out.
setup() {
  rm -rf "${w:?}/sys" "${w:?}/dev" "${w:?}/st" "${w:?}/bin" "${w:?}/build" "${w:?}/run"
  mkdir -p "$w/dev" "$w/st" "$w/bin" "$w/build" "$w/run" "$w/sys/block"
  cp "$script_src" "$w/run/stone-provision-ums.sh"
  cp "$lib_src" "$w/run/avocado-safe-disk.sh"
  cat >"$w/run/build-disk-image.sh" <<S
#!/bin/bash
echo "build" >> "$w/log"
: > "$w/build/nanopi.img"
echo "$w/build/nanopi.img"
S
  chmod +x "$w/run/build-disk-image.sh"
  echo '{}' >"$w/manifest.json"
  echo "overlay / overlay rw 0 0" >"$w/st/mounts"
  : >"$w/st/swaps"
  # The development host's own disk, which the wait must pass over.
  mkdisk sda "$ATAPATH" ATA "Samsung SSD 870"
  mkpart sda "$ATAPATH" sda1
  if [ "${1:-$USBPATH}" != none ]; then
    mkdisk sdb "${1:-$USBPATH}" Linux "UMS disk 0"
    mkpart sdb "${1:-$USBPATH}" sdb1
  fi
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
  cat >"$w/bin/mount" <<S
#!/bin/bash
cat "$w/st/mounts"
S
  # umount empties the mount table unless st/umount-noop exists.
  cat >"$w/bin/umount" <<S
#!/bin/bash
echo "umount \$*" >> "$w/log"
[ -e "$w/st/umount-noop" ] && exit 0
echo "overlay / overlay rw 0 0" > "$w/st/mounts"
S
  for t in dd sync; do
    cat >"$w/bin/$t" <<S
#!/bin/bash
echo "$t \$*" >> "$w/log"
exit 0
S
  done
  cat >"$w/bin/sleep" <<S
#!/bin/bash
exit 0
S
  cat >"$w/bin/sudo" <<S
#!/bin/bash
echo "sudo \$*" >> "$w/log"
exec "\$@"
S
  chmod +x "$w/bin/"*
}

base_env() {
  printf '%s\n' "PATH=$w/bin:$PATH" "SYSFS=$w/sys" "AVOCADO_PROVISION_SYSBLOCK=$w/sys/class/block" \
    "AVOCADO_SAFE_DISK_MOUNTS=$w/st/mounts" "AVOCADO_SAFE_DISK_SWAPS=$w/st/swaps" "AVOCADO_SAFE_DISK_DEVDIR=$w/dev" \
    "AVOCADO_SAFE_DISK_EUID=0" "AVOCADO_SAFE_DISK_CONTAINER_MARKERS=$w/no-marker" \
    "AVOCADO_STONE_MANIFEST=$w/manifest.json" "AVOCADO_STONE_BUILD_DIR=$w/build" "AVOCADO_STONE_DATA_DIR=$w"
}

# $1 = stdin (piped, so not a terminal), remaining args = extra env assignments.
run() {
  local input=$1 base
  shift
  mapfile -t base < <(base_env)
  : >"$w/log"
  printf '%b' "$input" | env "${base[@]}" "$@" bash "$w/run/stone-provision-ums.sh" 2>&1
}
# $1 = keystrokes, remaining args = extra env assignments; stdin is a terminal.
run_tty() {
  local input=$1 base
  shift
  mapfile -t base < <(base_env)
  : >"$w/log"
  run_with_tty "$input" env "${base[@]}" "$@" bash "$w/run/stone-provision-ums.sh" 2>&1
}
wrote() { grep -q "^dd " "$w/log"; }
wrote_to() { grep -q "^dd if=$w/build/nanopi.img of=$1 bs=4M oflag=direct conv=fsync\$" "$w/log"; }
built() { grep -q "^build" "$w/log"; }
usb() { echo "platform-fcd00000.usb-usb-0:1:1.0-scsi-0:0:0:0" >"$w/st/idpath-$1"; }
sata() { echo "pci-0000:00:17.0-ata-1" >"$w/st/idpath-$1"; }

# --- run modes: refused before the image is built or the disk is looked for ---

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_FWUP_TASK=upgrade AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! built && ! wrote && echo "$out" | grep -q "cannot honour AVOCADO_PROVISION_FWUP_TASK=upgrade"; } \
  && ok "FWUP_TASK=upgrade is refused naming upgrade, before the image is built" || bad "upgrade: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_FWUP_TASK=bogus AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! built && ! wrote && echo "$out" | grep -q "not valid"; } \
  && ok "an unknown FWUP_TASK is refused before any guard" || bad "bogus task: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_DRY_RUN=0 AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! built && ! wrote && echo "$out" | grep -q "not valid"; } \
  && ok "DRY_RUN=0 is refused before any guard" || bad "dry run 0: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_FORCE=yes)
rc=$?
{ [ $rc -ne 0 ] && ! built && ! wrote && echo "$out" | grep -q "AVOCADO_PROVISION_FORCE=yes is not valid"; } \
  && ok "FORCE=yes is refused before any guard" || bad "force yes: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_FWUP_TASK=complete AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb"; } \
  && ok "FWUP_TASK=complete proceeds to the write" || bad "complete: rc=$rc out=[$out] log=$(cat "$w/log")"

# --- the wait and the guards on the disk U-Boot exposes ----------------------

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb" && [ "$(grep -c '^dd ' "$w/log")" -eq 1 ]; } \
  && ok "the UMS disk, and only it, is written with FORCE=1 and no prompt" || bad "force pass: rc=$rc out=[$out] log=$(cat "$w/log")"
{ echo "$out" | grep -q "Target device: $w/dev/sdb" && echo "$out" | grep -q "Model: Linux UMS disk 0" \
  && echo "$out" | grep -q "Bus: .*usb"; } \
  && ok "the model, size and bus are shown before the write" || bad "identity: out=[$out]"

setup none
usb sda
out=$(run "" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "no 'Linux UMS disk 0' block device"; } \
  && ok "with no UMS disk the wait passes over the host's own disk and refuses" || bad "no ums disk: rc=$rc out=[$out]"

setup "$ATAPATH"
sata sdb
out=$(run "" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "not a USB or MMC bus"; } \
  && ok "a disk calling itself UMS disk 0 on a SATA bus is refused even with FORCE" || bad "sata: rc=$rc out=[$out]"

setup
usb sdb
echo "$w/dev/sdb1 / ext4 rw 0 0" >"$w/st/mounts"
out=$(run "" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "running root"; } \
  && ok "the disk holding / is refused even on a USB bus" || bad "root: rc=$rc out=[$out]"

setup
usb sdb
echo "$w/dev/sdb1 /media/card vfat rw 0 0" >>"$w/st/mounts"
out=$(run "" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -eq 0 ] && grep -q "^umount $w/dev/sdb" "$w/log" && wrote_to "$w/dev/sdb"; } \
  && ok "a partition mounted here is unmounted by the script and the write proceeds" || bad "unmount: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
usb sdb
echo "$w/dev/sdb1 /media/card vfat rw 0 0" >>"$w/st/mounts"
: >"$w/st/umount-noop"
out=$(run "" AVOCADO_PROVISION_FORCE=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "mounted or in use (mounts)"; } \
  && ok "a partition still mounted after the unmount step is refused" || bad "still mounted: rc=$rc out=[$out]"

setup
usb sdb
echo "$w/dev/sdb1 /run/media/user/card vfat rw 0 0" >"$w/st/host-mounts"
out=$(run "" AVOCADO_PROVISION_FORCE=1 AVOCADO_PROVISION_HOST_MOUNTS="$w/st/host-mounts")
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "mounted or in use (host-mounts)"; } \
  && ok "a host mount of the disk, from the exported table, is refused" || bad "host mount: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_FORCE=1 AVOCADO_PROVISION_HOST_MOUNTS="$w/st/absent")
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "cannot read $w/st/absent"; } \
  && ok "a named host mount table that cannot be read refuses" || bad "absent host table: rc=$rc out=[$out]"

# --- confirmation -------------------------------------------------------------

setup
usb sdb
out=$(run "y\n")
rc=$?
{ [ $rc -ne 0 ] && ! wrote; } \
  && ok "answering y does not confirm; nothing is written" || bad "y answer: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_FORCE=0)
rc=$?
{ [ $rc -ne 0 ] && ! wrote; } \
  && ok "FORCE=0 with no input at the prompt writes nothing" || bad "force 0 eof: rc=$rc out=[$out]"

setup
usb sdb
out=$(run_tty "$w/dev/sdb\n")
rc=$?
{ [ $rc -eq 0 ] && wrote_to "$w/dev/sdb"; } \
  && ok "on a terminal, retyping the device path confirms and writes" || bad "tty retype: rc=$rc out=[$out] log=$(cat "$w/log")"

setup
usb sdb
out=$(run_tty "/dev/sdb\n")
rc=$?
{ [ $rc -ne 0 ] && ! wrote; } \
  && ok "on a terminal, a wrong retype aborts" || bad "tty wrong: rc=$rc out=[$out]"

# --- dry run ------------------------------------------------------------------

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_DRY_RUN=1)
rc=$?
{ [ $rc -eq 0 ] && ! wrote && ! grep -q "^sync" "$w/log" \
  && echo "$out" | grep -q "dry-run: dd if=$w/build/nanopi.img of=$w/dev/sdb " \
  && [ "$(echo "$out" | tail -n 1)" = "dry run: nothing was written to $w/dev/sdb." ]; } \
  && ok "a dry run prints the dd, runs none of it, and ends naming the disk" || bad "dry run: rc=$rc out=[$out] log=$(cat "$w/log")"
echo "$out" | grep -q "Type the device path" \
  && bad "dry run asked for a retype: out=[$out]" || ok "a dry run does not ask for the retype"

setup "$ATAPATH"
sata sdb
out=$(run "" AVOCADO_PROVISION_DRY_RUN=1)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "not a USB or MMC bus"; } \
  && ok "a dry run still runs the bus guard and refuses" || bad "dry run sata: rc=$rc out=[$out]"

setup
usb sdb
echo "$w/dev/sdb1 /run/media/user/card vfat rw 0 0" >"$w/st/host-mounts"
out=$(run "" AVOCADO_PROVISION_DRY_RUN=1 AVOCADO_PROVISION_HOST_MOUNTS="$w/st/host-mounts")
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "mounted or in use (host-mounts)"; } \
  && ok "a dry run refuses a host-mounted disk" || bad "dry run host mount: rc=$rc out=[$out]"

# --- passthrough and privilege ------------------------------------------------

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_FORCE=1 AVOCADO_USB_PASSTHROUGH=0)
rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "needs the board's USB disk inside the SDK"; } \
  && ok "without USB passthrough the profile refuses" || bad "passthrough: rc=$rc out=[$out]"

setup
usb sdb
out=$(run "" AVOCADO_PROVISION_FORCE=1 AVOCADO_SAFE_DISK_EUID=1000)
rc=$?
{ [ $rc -eq 0 ] && grep -q "^sudo .*/dd if=$w/build/nanopi.img of=$w/dev/sdb " "$w/log" && wrote_to "$w/dev/sdb"; } \
  && ok "as a non-root user the write goes through sudo" || bad "sudo: rc=$rc out=[$out] log=$(cat "$w/log")"

echo
echo "passed: $pass  failed: $fail  (checks: $((pass + fail))/$total run)"
[ "$fail" -eq 0 ] && [ $((pass + fail)) -eq $total ]
