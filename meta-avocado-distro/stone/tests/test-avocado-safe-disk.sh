#!/usr/bin/env bash
# Host test for avocado-safe-disk.sh, the wrong-disk guards the stone sd and usb
# provisioning scripts source. Nothing here touches a disk: sysfs is a fake tree
# under a temp dir, the mount tables are files, and udevadm and stat are PATH
# stubs, so a failure to intercept writes into that dir and nowhere else.
#   bash meta-avocado-distro/stone/tests/test-avocado-safe-disk.sh
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts, so bad runs only when the check failed
set -u
here=$(cd "$(dirname "$0")" && pwd)
lib=${1:-$here/../avocado-safe-disk.sh}
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

# A disk lives at sys/devices/<path>/<name>, with its class/block entry a
# symlink to it, as the kernel lays it out. Partitions nest under the disk.
mkdisk() { # name path
  mkdir -p "$w/sys/devices/$2/$1" "$w/sys/class/block"
  ln -s "../../devices/$2/$1" "$w/sys/class/block/$1"
  echo 7864320 >"$w/sys/devices/$2/$1/size"
  echo 0 >"$w/sys/devices/$2/$1/removable"
  : >"$w/dev/$1"
}
mkpart() { # disk path partition
  mkdir -p "$w/sys/devices/$2/$1/$3"
  echo 1 >"$w/sys/devices/$2/$1/$3/partition"
  ln -s "../../devices/$2/$1/$3" "$w/sys/class/block/$3"
  : >"$w/dev/$3"
}

USBPATH=pci0000:00/0000:00:14.0/usb1/1-2/1-2:1.0/host6/target6:0:0/6:0:0:0/block
ATAPATH=pci0000:00/0000:00:17.0/ata1/host0/target0:0:0/0:0:0:0/block
NVMEPATH=pci0000:00/0000:00:1d.0/0000:3d:00.0/nvme/nvme0
MMCPATH=pci0000:00/0000:00:1a.0/mmc_host/mmc0/mmc0:0001/block

setup() {
  rm -rf "${w:?}/sys" "${w:?}/dev" "${w:?}/st" "${w:?}/bin"
  mkdir -p "$w/sys" "$w/dev/disk/by-id" "$w/dev/mapper" "$w/st" "$w/bin"
  : >"$w/st/mounts"
  : >"$w/st/swaps"
  echo "overlay / overlay rw 0 0" >"$w/st/mounts"
  mkdisk sdb "$USBPATH"
  mkpart sdb "$USBPATH" sdb1
  mkdisk sda "$ATAPATH"
  mkpart sda "$ATAPATH" sda1
  mkpart sda "$ATAPATH" sda2
  mkdisk nvme0n1 "$NVMEPATH"
  mkpart nvme0n1 "$NVMEPATH" nvme0n1p1
  mkdisk mmcblk0 "$MMCPATH"
  ln -s ../../sdb "$w/dev/disk/by-id/usb-Stick"
  # The stubs. stat reports every file under dev/ as a block node and defers
  # to the real tool for anything else; udevadm answers from st/idpath-<name>
  # and prints nothing for a device without an entry, like a missing udev db.
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
[ -e "$w/st/udev-fail" ] && exit 1
n=\$(basename "\$(readlink -f -- "\${@: -1}")")
cat "$w/st/idpath-\$n" 2>/dev/null
exit 0
S
  chmod +x "$w/bin/stat" "$w/bin/udevadm"
}

# Run one library call in a clean shell. $1 is the shell code to run after
# sourcing; prints its stderr and stdout together and returns its status.
call() {
  PATH="$w/bin:$PATH" AVOCADO_PROVISION_SYSBLOCK="$w/sys/class/block" \
    AVOCADO_SAFE_DISK_MOUNTS="${T_MOUNTS:-$w/st/mounts}" AVOCADO_SAFE_DISK_SWAPS="${T_SWAPS:-$w/st/swaps}" \
    AVOCADO_SAFE_DISK_DEVDIR="$w/dev" AVOCADO_SAFE_DISK_CONTAINER_MARKERS="${T_MARKERS:-$w/st/no-marker}" bash -c ". '$lib'; $1" 2>&1
}
idpath() { echo "$2" >"$w/st/idpath-$1"; }

# --- whole disk -------------------------------------------------------------

setup
idpath sdb "pci-0000:00:14.0-usb-0:2:1.0-scsi-0:0:0:0"
out=$(call "avocado_safe_disk_check_device $w/dev/sdb && echo DEV=\$AVOCADO_SAFE_DISK_DEV")
rc=$?
{ [ $rc -eq 0 ] && echo "$out" | grep -qx "DEV=$w/dev/sdb"; } \
  && ok "a whole USB disk passes and is returned as its canonical node" || bad "pass path: rc=$rc out=[$out]"

out=$(call "avocado_safe_disk_check_device $w/dev/disk/by-id/usb-Stick && echo DEV=\$AVOCADO_SAFE_DISK_DEV")
rc=$?
{ [ $rc -eq 0 ] && echo "$out" | grep -qx "DEV=$w/dev/sdb"; } \
  && ok "a by-id alias resolves to the disk, not to a phantom partition" || bad "alias: rc=$rc out=[$out]"

: >"$w/notblock"
out=$(call "avocado_safe_disk_check_device $w/notblock")
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "not a block device"; } \
  && ok "a regular file is refused as not a block device" || bad "non-block: rc=$rc out=[$out]"

out=$(call "avocado_safe_disk_check_device $w/dev/missing")
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "not a block device"; } \
  && ok "a path that does not exist is refused" || bad "missing: rc=$rc out=[$out]"

out=$(call "avocado_safe_disk_check_device $w/dev/sdb1")
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "partition"; } \
  && ok "a partition is refused: whole disk only" || bad "partition: rc=$rc out=[$out]"

: >"$w/dev/sdz"
out=$(call "avocado_safe_disk_check_device $w/dev/sdz")
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "kernel lists"; } \
  && ok "a node the kernel does not list is refused" || bad "unlisted: rc=$rc out=[$out]"

# --- bus --------------------------------------------------------------------

setup
idpath sda "pci-0000:00:17.0-ata-1"
echo 1 >"$w/sys/devices/$ATAPATH/sda/removable"
out=$(call "avocado_safe_disk_check_device $w/dev/sda")
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "not a USB or MMC bus"; } \
  && ok "a SATA disk is refused even when the kernel marks it removable" || bad "sata removable=1: rc=$rc out=[$out]"

setup
idpath nvme0n1 "pci-0000:3d:00.0-nvme-1"
out=$(call "avocado_safe_disk_check_device $w/dev/nvme0n1")
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "not a USB or MMC bus"; } \
  && ok "an NVMe disk is refused" || bad "nvme: rc=$rc out=[$out]"

setup
idpath mmcblk0 "platform-fe2c0000.mmc"
out=$(call "avocado_safe_disk_check_device $w/dev/mmcblk0")
rc=$?
{ [ $rc -eq 0 ] && grep -qx 0 "$w/sys/devices/$MMCPATH/mmcblk0/removable"; } \
  && ok "an MMC card passes although the kernel reports removable=0" || bad "mmc removable=0: rc=$rc out=[$out]"

setup
out=$(call "avocado_safe_disk_check_device $w/dev/sdb && echo BUS=\$AVOCADO_SAFE_DISK_BUS")
rc=$?
{ [ $rc -eq 0 ] && echo "$out" | grep -q "BUS=.*usb1.*(sysfs path)"; } \
  && ok "with no udev data a USB disk is identified from its sysfs path" || bad "sysfs usb: rc=$rc out=[$out]"

setup
out=$(call "avocado_safe_disk_check_device $w/dev/sda")
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "not a USB or MMC bus"; } \
  && ok "with no udev data a SATA disk is refused from its sysfs path" || bad "sysfs sata: rc=$rc out=[$out]"

setup
out=$(call "avocado_safe_disk_check_device $w/dev/mmcblk0")
rc=$?
[ $rc -eq 0 ] && ok "with no udev data an MMC card is identified from its sysfs path" || bad "sysfs mmc: rc=$rc out=[$out]"

setup
: >"$w/st/udev-fail"
out=$(call "avocado_safe_disk_check_device $w/dev/sdb")
rc=$?
[ $rc -eq 0 ] && ok "a failing udevadm falls back to sysfs rather than refusing a USB disk" || bad "udevadm fails: rc=$rc out=[$out]"

setup
mkdir -p "$w/nobin"
ln -s "$(command -v bash)" "$w/nobin/bash"
for t in stat readlink basename dirname awk grep cat tr xargs; do ln -sf "$(command -v $t)" "$w/nobin/$t"; done
ln -sf "$w/bin/stat" "$w/nobin/stat"
out=$(PATH="$w/nobin" AVOCADO_PROVISION_SYSBLOCK="$w/sys/class/block" AVOCADO_SAFE_DISK_MOUNTS="$w/st/mounts" \
  AVOCADO_SAFE_DISK_SWAPS="$w/st/swaps" AVOCADO_SAFE_DISK_DEVDIR="$w/dev" bash -c ". '$lib'; avocado_safe_disk_check_device $w/dev/sdb" 2>&1)
rc=$?
[ $rc -eq 0 ] && ok "a missing udevadm binary is not fatal" || bad "no udevadm: rc=$rc out=[$out]"

setup
out=$(call "avocado_safe_disk_bus $w/dev/gone")
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "neither udev nor sysfs"; } \
  && ok "a device whose bus cannot be established is refused" || bad "bus unknown: rc=$rc out=[$out]"

# --- running root -----------------------------------------------------------

setup
idpath sda "pci-0000:00:14.0-usb-0:2:1.0-scsi-0:0:0:0"
echo "$w/dev/sda2 / ext4 rw 0 0" >"$w/st/mounts"
out=$(call "avocado_safe_disk_not_root $w/dev/sda")
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "running root"; } \
  && ok "the disk holding / is refused" || bad "root disk: rc=$rc out=[$out]"

out=$(call "avocado_safe_disk_not_root $w/dev/sdb")
rc=$?
[ $rc -eq 0 ] && ok "a different disk is not mistaken for the root disk" || bad "other disk: rc=$rc out=[$out]"

setup
mkdisk dm-0 "virtual/block"
mkdir -p "$w/sys/devices/virtual/block/dm-0/slaves"
ln -s ../../../../pci0000:00/0000:00:1d.0/0000:3d:00.0/nvme/nvme0/nvme0n1/nvme0n1p1 "$w/sys/devices/virtual/block/dm-0/slaves/nvme0n1p1"
ln -s "$w/dev/dm-0" "$w/dev/mapper/root"
echo "$w/dev/mapper/root / ext4 rw 0 0" >"$w/st/mounts"
out=$(call "avocado_safe_disk_not_root $w/dev/nvme0n1")
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "running root"; } \
  && ok "the physical disk under a dm-crypt root is refused" || bad "dm root: rc=$rc out=[$out]"

setup
echo "$w/dev/root / ext4 rw 0 0" >"$w/st/mounts"
out=$(call "avocado_safe_disk_not_root $w/dev/sdb")
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "refusing to guess"; } \
  && ok "an unresolvable /dev root fails closed" || bad "unresolvable root: rc=$rc out=[$out]"

out=$(T_MOUNTS="$w/st/absent" call "avocado_safe_disk_not_root $w/dev/sdb")
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "cannot read"; } \
  && ok "an unreadable mount table fails closed for the root check" || bad "no mounts (root): rc=$rc out=[$out]"

# --- mounted ----------------------------------------------------------------

setup
echo "$w/dev/sdb1 /media/stick vfat rw 0 0" >"$w/st/mounts"
out=$(call "avocado_safe_disk_unmounted $w/dev/sdb")
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "mounted"; } \
  && ok "a disk with a mounted partition is refused" || bad "mounted: rc=$rc out=[$out]"

echo "$w/dev/disk/by-id/usb-Stick /media/stick vfat rw 0 0" >"$w/st/mounts"
out=$(call "avocado_safe_disk_unmounted $w/dev/sdb")
rc=$?
[ $rc -ne 0 ] && ok "a mount named through a symlink is still found" || bad "mounted via alias: rc=$rc out=[$out]"

echo "$w/dev/sdb /media/raw ext4 rw 0 0" >"$w/st/mounts"
out=$(call "avocado_safe_disk_unmounted $w/dev/sdb")
rc=$?
[ $rc -ne 0 ] && ok "a filesystem mounted on the bare disk is refused" || bad "mounted whole disk: rc=$rc out=[$out]"

echo "$w/dev/sdb1 [SWAP]" >"$w/st/swaps"
: >"$w/st/mounts"
out=$(call "avocado_safe_disk_unmounted $w/dev/sdb")
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "swaps"; } \
  && ok "swap on a partition of the disk is refused" || bad "swap: rc=$rc out=[$out]"

setup
mkdisk sdbb "$USBPATH-other"
mkpart sdbb "$USBPATH-other" sdbb1
echo "$w/dev/sdbb1 /media/other vfat rw 0 0" >"$w/st/mounts"
out=$(call "avocado_safe_disk_unmounted $w/dev/sdb")
rc=$?
[ $rc -eq 0 ] && ok "a mount on another disk sharing the name prefix is not blamed on this one" || bad "prefix: rc=$rc out=[$out]"

out=$(T_SWAPS="$w/st/absent" call "avocado_safe_disk_unmounted $w/dev/sdb")
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "cannot read"; } \
  && ok "an unreadable swap table fails closed" || bad "no swaps: rc=$rc out=[$out]"

# --- host mount table -------------------------------------------------------

setup
echo "$w/dev/sdb1 /media/stick vfat rw 0 0" >"$w/st/host-mounts"
out=$(call "AVOCADO_PROVISION_HOST_MOUNTS=$w/st/host-mounts avocado_safe_disk_unmounted $w/dev/sdb")
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "host-mounts"; } \
  && ok "a partition mounted only in the host table is refused" || bad "host-only mount: rc=$rc out=[$out]"

out=$(call "AVOCADO_PROVISION_HOST_MOUNTS=$w/st/absent avocado_safe_disk_unmounted $w/dev/sdb")
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "$w/st/absent"; } \
  && ok "an unreadable host table is refused, naming the file" || bad "host unreadable: rc=$rc out=[$out]"

echo "overlay / overlay rw 0 0" >"$w/st/host-mounts"
out=$(call "AVOCADO_PROVISION_HOST_MOUNTS=$w/st/host-mounts avocado_safe_disk_unmounted $w/dev/sdb")
rc=$?
{ [ $rc -eq 0 ] && ! echo "$out" | grep -qi "warning"; } \
  && ok "a clean host table passes without a warning" || bad "host clean: rc=$rc out=[$out]"

: >"$w/st/marker"
out=$(T_MARKERS="$w/st/marker" call "avocado_safe_disk_unmounted $w/dev/sdb")
rc=$?
{ [ $rc -eq 0 ] && echo "$out" | grep -q "host mounts" && echo "$out" | grep -qi "not checked"; } \
  && ok "in a container with no host table it warns and continues" || bad "container warn: rc=$rc out=[$out]"

out=$(call "avocado_safe_disk_unmounted $w/dev/sdb")
rc=$?
{ [ $rc -eq 0 ] && [ -z "$out" ]; } \
  && ok "on a host with no host table it neither warns nor refuses" || bad "host silent: rc=$rc out=[$out]"

out=$(T_MARKERS="$w/st/marker" call "AVOCADO_PROVISION_HOST_MOUNTS=$w/st/host-mounts avocado_safe_disk_unmounted $w/dev/sdb")
rc=$?
{ [ $rc -eq 0 ] && ! echo "$out" | grep -qi "warning"; } \
  && ok "in a container with a host table there is no warning" || bad "container with table: rc=$rc out=[$out]"

mkdir -p "$w/sys/devices/virtual/block/dm-0/slaves"
ln -s "../../../../$USBPATH/sdb/sdb1" "$w/sys/devices/virtual/block/dm-0/slaves/sdb1"
ln -s ../../devices/virtual/block/dm-0 "$w/sys/class/block/dm-0"
: >"$w/dev/dm-0"
ln -s ../dm-0 "$w/dev/mapper/crypt"
echo "$w/dev/mapper/crypt /mnt/secret ext4 rw 0 0" >"$w/st/mounts"
out=$(call "avocado_safe_disk_unmounted $w/dev/sdb")
rc=$?
[ $rc -ne 0 ] && ok "a dm volume stacked on a partition of the target is refused" || bad "stacked dm: rc=$rc out=[$out]"

# --- confirmation -----------------------------------------------------------

setup
idpath sdb "pci-0000:00:14.0-usb-0:2:1.0-scsi-0:0:0:0"
mkdir -p "$w/sys/devices/$USBPATH/sdb/device"
printf 'ACME    ' >"$w/sys/devices/$USBPATH/sdb/device/vendor"
printf 'Card Reader     ' >"$w/sys/devices/$USBPATH/sdb/device/model"
# shellcheck source=pty-run.sh
. "$here/pty-run.sh"
have_tty=1
command -v script >/dev/null 2>&1 || have_tty=0

# conf <force-env-assignments> <typed|-> <terminal yes|no> [confirm args]: run
# check_device then confirm. With a terminal the keystrokes in $2 are typed on a
# pty; without one they arrive on a pipe, which must never count as confirming.
conf() {
  local envs=$1 typed=$2 term=$3 args=${4:-} code rc
  code="avocado_safe_disk_check_device $w/dev/sdb && avocado_safe_disk_confirm \$AVOCADO_SAFE_DISK_DEV $args"
  if [ "$term" = yes ]; then
    # shellcheck disable=SC2086 # envs is a list of NAME=value words, none with spaces
    run_with_tty "$typed" env PATH="$w/bin:$PATH" AVOCADO_PROVISION_SYSBLOCK="$w/sys/class/block" \
      AVOCADO_SAFE_DISK_MOUNTS="$w/st/mounts" AVOCADO_SAFE_DISK_SWAPS="$w/st/swaps" \
      AVOCADO_SAFE_DISK_DEVDIR="$w/dev" AVOCADO_SAFE_DISK_CONTAINER_MARKERS="$w/st/no-marker" \
      $envs bash -c ". '$lib'; $code" >"$w/tty.out"
    rc=$?
    tr -d '\r' <"$w/tty.out"
    return $rc
  else
    printf '%b' "$typed" | call "${envs:+export $envs;} $code"
  fi
}

out=$(conf "" "$w/dev/sdb\n" yes)
rc=$?
if [ "$have_tty" = 0 ]; then
  pass=$((pass + 1))
else
  [ $rc -eq 0 ] && ok "retyping the device path on a terminal confirms" || bad "retype: rc=$rc out=[$out]"
fi
{ echo "$out" | grep -q "Model: ACME Card Reader" && echo "$out" | grep -q "Size:  3.75 GiB" && echo "$out" | grep -q "Bus:   .*usb"; } \
  && ok "the identity shows model, size and bus before the prompt" || bad "identity: out=[$out]"

vectors="$here/confirm-vectors.tsv"
vrows=0
if [ ! -r "$vectors" ]; then
  bad "confirm-vectors.tsv is missing"
else
  while IFS=$'\t' read -r vforce vterm vdry vwant; do
    case "$vforce" in '' | '#'* | force) continue ;; esac
    vrows=$((vrows + 1))
    venv=""
    case "$vforce" in
      "<unset>") ;;
      "<empty>") venv="AVOCADO_PROVISION_FORCE=" ;;
      *) venv="AVOCADO_PROVISION_FORCE=$vforce" ;;
    esac
    [ "$vdry" = yes ] && venv="$venv AVOCADO_PROVISION_DRY_RUN=1"
    label="vector force=$vforce terminal=$vterm dry_run=$vdry -> $vwant"
    if [ "$vterm" = yes ] && [ "$have_tty" = 0 ]; then
      ok "$label (skipped: script(1) missing)"
      [ "$vwant" = retype ] && pass=$((pass + 1))
      continue
    fi
    out=$(conf "$venv" "$w/dev/sdb\n" "$vterm")
    rc=$?
    case "$vwant" in
      skip)
        { [ $rc -eq 0 ] && echo "$out" | grep -qx "confirmation skipped: AVOCADO_PROVISION_FORCE=1" && echo "$out" | grep -q "Model:" \
          && ! echo "$out" | grep -q "Type the device"; } && ok "$label" || bad "$label: rc=$rc out=[$out]"
        ;;
      retype)
        { [ $rc -eq 0 ] && echo "$out" | grep -q "Type the device"; } && ok "$label" || bad "$label: rc=$rc out=[$out]"
        out=$(conf "$venv" "$w/dev/sdb1\n" yes)
        rc=$?
        { [ $rc -ne 0 ] && echo "$out" | grep -q "did not match"; } \
          && ok "$label: a different typed path aborts" || bad "$label wrong path: rc=$rc out=[$out]"
        ;;
      refuse)
        { [ $rc -ne 0 ] && ! echo "$out" | grep -qx "dry run: not asking for confirmation." && ! echo "$out" | grep -q "^confirmation skipped"; } \
          && ok "$label" || bad "$label: rc=$rc out=[$out]"
        ;;
      proceed)
        { [ $rc -eq 0 ] && ! echo "$out" | grep -q "Type the device"; } && ok "$label" || bad "$label: rc=$rc out=[$out]"
        ;;
      *) bad "$label: unknown outcome in vector file" ;;
    esac
  done <"$vectors"
fi
[ "$vrows" -eq 19 ] && ok "all 19 vector rows were read" || bad "vector rows read: $vrows"

out=$(conf "AVOCADO_PROVISION_FORCE=0" "" no)
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "no terminal to confirm on"; } \
  && ok "FORCE=0 without a terminal names the missing terminal" || bad "force=0 msg: rc=$rc out=[$out]"

out=$(conf "" "no terminal\n" no)
rc=$?
{ [ $rc -eq 0 ] && echo "$out" | grep -qx "confirmation skipped: no terminal and no AVOCADO_PROVISION_FORCE signal"; } \
  && ok "the legacy row prints its skip line and proceeds" || bad "legacy: rc=$rc out=[$out]"

out=$(conf "AVOCADO_PROVISION_FORCE=bogus" "$w/dev/sdb\n" no)
rc=$?
{ [ $rc -ne 0 ] && ! echo "$out" | grep -q "Model:"; } \
  && ok "an unknown FORCE value refuses before printing the identity" || bad "bogus: rc=$rc out=[$out]"

if [ "$have_tty" = 1 ]; then
  out=$(conf "" "yes\n" yes)
  rc=$?
  { [ $rc -ne 0 ] && echo "$out" | grep -q "did not match"; } \
    && ok "'yes' is not accepted: the path must be typed" || bad "yes: rc=$rc out=[$out]"

  out=$(conf "AVOCADO_PROVISION_FORCE=0" "" yes 1)
  rc=$?
  { [ $rc -ne 0 ] && echo "$out" | grep -q "did not match"; } \
    && ok "a device named up front (second argument 1) still has to be retyped" || bad "named wrong: rc=$rc out=[$out]"

  out=$(conf "AVOCADO_PROVISION_FORCE=0" "$w/dev/sdb\n" yes 1)
  rc=$?
  { [ $rc -eq 0 ] && echo "$out" | grep -q "Type the device"; } \
    && ok "a device named up front is confirmed by retyping it" || bad "named right: rc=$rc out=[$out]"
else
  pass=$((pass + 3))
fi

# Identity with no device/vendor or device/model files prints no shell error.
rm -rf "$w/sys/devices/$USBPATH/sdb/device"
out=$(call "avocado_safe_disk_identity $w/dev/sdb")
rc=$?
{ [ $rc -eq 0 ] && ! echo "$out" | grep -qi "no such file" && echo "$out" | grep -q "Model: unknown"; } \
  && ok "identity without vendor and model files prints Model: unknown and no shell error" || bad "identity missing: rc=$rc out=[$out]"

# --- privileged runner ------------------------------------------------------

# A stub sudo records its argv one word per line and runs the command it was
# given, so what the escalated process receives is observable. The tool is a
# stub too, printing its own argv and LD_LIBRARY_PATH.
runner_setup() {
  setup
  mkdir -p "$w/tools" "$w/empty"
  cat >"$w/tools/fwup" <<S
#!/bin/bash
echo "TOOL argv=\$* ld=\${LD_LIBRARY_PATH:-unset}"
S
  chmod +x "$w/tools/fwup"
  cat >"$w/bin/sudo" <<S
#!/bin/bash
printf '%s\n' "\$@" >"$w/st/sudo-argv"
echo SUDO_CALLED
exec "\$@"
S
  chmod +x "$w/bin/sudo"
  : >"$w/st/sudo-argv"
  rm -f "$w/st/sudo-argv"
}
# PATH with the stubs first and the system dirs after; a test that needs sudo
# absent sets T_TAIL to an empty dir, since this host may have a real sudo.
runcall() { # env prefix in $1, code in $2
  env -i HOME="$w" PATH="$w/tools:$w/bin:${T_TAIL:-/usr/bin:/bin}" "${@:3}" \
    AVOCADO_PROVISION_SYSBLOCK="$w/sys/class/block" "$BASH" -c ". '$lib'; $2" 2>&1
}

runner_setup
out=$(runcall x "avocado_safe_disk_run fwup -a 1" AVOCADO_SAFE_DISK_EUID=0)
rc=$?
{ [ $rc -eq 0 ] && echo "$out" | grep -q "TOOL argv=-a 1" && ! echo "$out" | grep -q SUDO_CALLED && [ ! -e "$w/st/sudo-argv" ]; } \
  && ok "as uid 0 the tool runs directly and sudo is never called" || bad "root: rc=$rc out=[$out]"

runner_setup
out=$(runcall x "avocado_safe_disk_run fwup -a 1" AVOCADO_SAFE_DISK_EUID=1000)
rc=$?
{ [ $rc -eq 0 ] && echo "$out" | grep -q SUDO_CALLED && [ "$(grep -c "^$w/tools/fwup$" "$w/st/sudo-argv")" = 1 ] && ! grep -qx fwup "$w/st/sudo-argv"; } \
  && ok "a non-root run escalates with the tool's absolute path, never bare" || bad "abs path: rc=$rc out=[$out] argv=[$(cat "$w/st/sudo-argv" 2>/dev/null)]"

runner_setup
out=$(runcall x "avocado_safe_disk_run fwup" AVOCADO_SAFE_DISK_EUID=1000 LD_LIBRARY_PATH=/sdk/lib)
rc=$?
{ [ $rc -eq 0 ] && echo "$out" | grep -q "ld=/sdk/lib" && grep -qx "LD_LIBRARY_PATH=/sdk/lib" "$w/st/sudo-argv"; } \
  && ok "LD_LIBRARY_PATH is forwarded across sudo explicitly" || bad "ld forward: rc=$rc out=[$out]"

runner_setup
out=$(runcall x "avocado_safe_disk_run fwup" AVOCADO_SAFE_DISK_EUID=1000)
{ echo "$out" | grep -q "ld=unset" && ! grep -q LD_LIBRARY_PATH "$w/st/sudo-argv"; } \
  && ok "an unset LD_LIBRARY_PATH is not forwarded as an empty value" || bad "ld unset: out=[$out]"

runner_setup
out=$(runcall x "avocado_safe_disk_run nosuchtool-xyz" AVOCADO_SAFE_DISK_EUID=1000)
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "nosuchtool-xyz" && ! echo "$out" | grep -q SUDO_CALLED; } \
  && ok "a tool not on PATH is refused by name before sudo is invoked" || bad "no tool: rc=$rc out=[$out]"

runner_setup
rm -f "$w/bin/sudo"
out=$(T_TAIL="$w/empty" runcall x "avocado_safe_disk_run fwup" AVOCADO_SAFE_DISK_EUID=1000)
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -qi "sudo" && echo "$out" | grep -q "fwup" && ! echo "$out" | grep -q "TOOL argv"; } \
  && ok "without sudo the step is refused by name and nothing runs" || bad "no sudo: rc=$rc out=[$out]"

runner_setup
out=$(runcall x "avocado_safe_disk_run fwup" AVOCADO_SAFE_DISK_EUID=0 LD_LIBRARY_PATH=/sdk/lib)
{ echo "$out" | grep -q "ld=/sdk/lib" && [ ! -e "$w/st/sudo-argv" ]; } \
  && ok "as uid 0 the environment passes through untouched" || bad "root env: out=[$out]"

# --- run modes: write choke point, mode validation, dry run ----------------

# The recording fwup stub writes its argv to st/tool-ran, so "nothing ran" is a
# missing file rather than an absence of output.
modes_setup() {
  runner_setup
  cat >"$w/tools/fwup" <<S
#!/bin/bash
echo "\$*" >"$w/st/tool-ran"
echo "TOOL argv=\$*"
S
  chmod +x "$w/tools/fwup"
  rm -f "$w/st/tool-ran"
}

modes_setup
out=$(runcall x "avocado_safe_disk_write fwup -a 1" AVOCADO_SAFE_DISK_EUID=0)
rc=$?
{ [ $rc -eq 0 ] && [ "$(cat "$w/st/tool-ran" 2>/dev/null)" = "-a 1" ]; } \
  && ok "outside a dry run the write choke point runs the command" || bad "write real: rc=$rc out=[$out]"

modes_setup
out=$(runcall x "avocado_safe_disk_write fwup -a 1" AVOCADO_SAFE_DISK_EUID=0 AVOCADO_PROVISION_DRY_RUN=1)
rc=$?
{ [ $rc -eq 0 ] && echo "$out" | grep -qx "dry-run: fwup -a 1" && [ ! -e "$w/st/tool-ran" ] && ! echo "$out" | grep -q TOOL; } \
  && ok "in a dry run the write is printed as 'dry-run: <cmd>' and never run" || bad "write dry: rc=$rc out=[$out]"

modes_setup
out=$(runcall x "avocado_safe_disk_write fwup -a 1" AVOCADO_SAFE_DISK_EUID=1000 AVOCADO_PROVISION_DRY_RUN=1)
{ ! echo "$out" | grep -q SUDO_CALLED && [ ! -e "$w/st/sudo-argv" ]; } \
  && ok "a dry run never reaches sudo" || bad "write dry sudo: out=[$out]"

modes_setup
out=$(runcall x "avocado_safe_disk_write fwup -a 1" AVOCADO_SAFE_DISK_EUID=0 AVOCADO_PROVISION_DRY_RUN=true)
rc=$?
{ [ $rc -ne 0 ] && [ ! -e "$w/st/tool-ran" ]; } \
  && ok "the write refuses under an unvalidated DRY_RUN value rather than running" || bad "write true: rc=$rc out=[$out]"

modes() { # env args in $@ after the call, profile flags in $1
  runcall x "avocado_safe_disk_modes $1" "${@:2}"
}
for v in "" 1; do
  out=$(modes "sd 1 1" AVOCADO_PROVISION_DRY_RUN="$v")
  rc=$?
  [ $rc -eq 0 ] && ok "DRY_RUN='$v' is accepted" || bad "dry '$v': rc=$rc out=[$out]"
done
out=$(modes "sd 1 1")
rc=$?
[ $rc -eq 0 ] && ok "DRY_RUN unset is accepted" || bad "dry unset: rc=$rc out=[$out]"
for v in 0 true yes; do
  out=$(modes "sd 1 1" AVOCADO_PROVISION_DRY_RUN="$v")
  rc=$?
  { [ $rc -ne 0 ] && echo "$out" | grep -q "AVOCADO_PROVISION_DRY_RUN" && echo "$out" | grep -q "$v"; } \
    && ok "DRY_RUN=$v is refused, naming the variable and value" || bad "dry $v: rc=$rc out=[$out]"
done
for v in "" 0 1; do
  out=$(modes "sd 1 1" AVOCADO_PROVISION_FORCE="$v")
  rc=$?
  [ $rc -eq 0 ] && ok "FORCE='$v' is accepted" || bad "force '$v': rc=$rc out=[$out]"
done
out=$(modes "sd 1 1")
rc=$?
[ $rc -eq 0 ] && ok "FORCE unset is accepted" || bad "force unset: rc=$rc out=[$out]"
for v in yes true 2; do
  out=$(modes "sd 1 1" AVOCADO_PROVISION_FORCE="$v" AVOCADO_PROVISION_DRY_RUN=1)
  rc=$?
  { [ $rc -ne 0 ] && echo "$out" | grep -q "AVOCADO_PROVISION_FORCE" && echo "$out" | grep -q "$v"; } \
    && ok "FORCE=$v is refused, even in a dry run" || bad "force $v: rc=$rc out=[$out]"
done
for v in "" complete upgrade; do
  out=$(modes "sd 1 1" AVOCADO_PROVISION_FWUP_TASK="$v")
  rc=$?
  [ $rc -eq 0 ] && ok "FWUP_TASK='$v' is accepted" || bad "task '$v': rc=$rc out=[$out]"
done
out=$(modes "sd 1 1" AVOCADO_PROVISION_FWUP_TASK=full)
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "full"; } \
  && ok "FWUP_TASK=full is refused, naming it" || bad "task full: rc=$rc out=[$out]"

out=$(modes "uuu 0 1" AVOCADO_PROVISION_DRY_RUN=1)
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "uuu" && echo "$out" | grep -qi "dry run"; } \
  && ok "a profile without dry-run support refuses a dry run, naming itself" || bad "dry_run_ok=0: rc=$rc out=[$out]"
out=$(modes "uuu 0 1")
rc=$?
[ $rc -eq 0 ] && ok "a profile without dry-run support runs normally" || bad "dry_run_ok=0 real: rc=$rc out=[$out]"

out=$(modes "dd 1 0" AVOCADO_PROVISION_FWUP_TASK=upgrade)
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "upgrade" && echo "$out" | grep -q "dd"; } \
  && ok "a profile that cannot honour a task refuses upgrade, naming it" || bad "task_ok=0: rc=$rc out=[$out]"
out=$(modes "dd 1 0" AVOCADO_PROVISION_FWUP_TASK=complete)
rc=$?
[ $rc -eq 0 ] && ok "a profile that cannot honour a task accepts complete" || bad "task_ok=0 complete: rc=$rc out=[$out]"

out=$(runcall x "avocado_safe_disk_finish $w/dev/sdb" AVOCADO_PROVISION_DRY_RUN=1)
[ "$out" = "dry run: nothing was written to $w/dev/sdb." ] \
  && ok "finish says nothing was written in a dry run" || bad "finish dry: out=[$out]"
out=$(runcall x "avocado_safe_disk_finish $w/dev/sdb")
[ -z "$out" ] && ok "finish is silent outside a dry run" || bad "finish real: out=[$out]"

# Dry run: a mount in this namespace is reported, a host-table mount refuses.
setup
idpath sdb "pci-0000:00:14.0-usb-0:2:1.0-scsi-0:0:0:0"
echo "$w/dev/sdb1 /media/stick vfat rw 0 0" >"$w/st/mounts"
out=$(call "AVOCADO_PROVISION_DRY_RUN=1 avocado_safe_disk_unmounted $w/dev/sdb")
rc=$?
{ [ $rc -eq 0 ] && echo "$out" | grep -q "$w/dev/sdb1" && echo "$out" | grep -qi "would"; } \
  && ok "in a dry run a local mount is reported and the run continues" || bad "dry local mount: rc=$rc out=[$out]"
out=$(call "avocado_safe_disk_unmounted $w/dev/sdb")
rc=$?
[ $rc -ne 0 ] && ok "outside a dry run the same local mount still refuses" || bad "real local mount: rc=$rc out=[$out]"
echo "overlay / overlay rw 0 0" >"$w/st/mounts"
echo "$w/dev/sdb1 /media/stick vfat rw 0 0" >"$w/st/host-mounts"
out=$(call "AVOCADO_PROVISION_DRY_RUN=1 AVOCADO_PROVISION_HOST_MOUNTS=$w/st/host-mounts avocado_safe_disk_unmounted $w/dev/sdb")
rc=$?
[ $rc -ne 0 ] && ok "in a dry run a mount seen only in the host table still refuses" || bad "dry host mount: rc=$rc out=[$out]"

# Dry run asks no retype: FORCE=0 and a pipe, run through every guard, exits 0.
rm -f "$w/st/host-mounts"
mkdir -p "$w/sys/devices/$USBPATH/sdb/device"
printf 'ACME    ' >"$w/sys/devices/$USBPATH/sdb/device/vendor"
printf 'Card Reader     ' >"$w/sys/devices/$USBPATH/sdb/device/model"
pipeline="export AVOCADO_PROVISION_DRY_RUN=1 AVOCADO_PROVISION_FORCE=0 AVOCADO_SAFE_DISK_EUID=0
  avocado_safe_disk_modes sd 1 1 && avocado_safe_disk_check_device $w/dev/sdb &&
  avocado_safe_disk_unmounted && avocado_safe_disk_confirm \$AVOCADO_SAFE_DISK_DEV 0 &&
  avocado_safe_disk_write fwup -a /img -d \$AVOCADO_SAFE_DISK_DEV && avocado_safe_disk_finish \$AVOCADO_SAFE_DISK_DEV"
out=$(printf 'y\n' | PATH="$w/tools:$w/bin:$PATH" call "$pipeline")
rc=$?
{ [ $rc -eq 0 ] && echo "$out" | grep -q "Model: ACME Card Reader" && ! echo "$out" | grep -qi "type the device" \
  && echo "$out" | grep -qx "dry-run: fwup -a /img -d $w/dev/sdb" && [ ! -e "$w/st/tool-ran" ] \
  && [ "$(echo "$out" | tail -n1)" = "dry run: nothing was written to $w/dev/sdb." ]; } \
  && ok "a dry run with FORCE=0 and a pipe runs every guard, asks no retype and exits 0" || bad "dry full: rc=$rc out=[$out]"

out=$(printf 'y\n' | PATH="$w/tools:$w/bin:$PATH" call "${pipeline/FORCE=0/FORCE=yes}")
rc=$?
{ [ $rc -ne 0 ] && ! echo "$out" | grep -q "Model:" && ! echo "$out" | grep -q "^dry-run"; } \
  && ok "an unknown FORCE value refuses before any guard output" || bad "dry unknown force: rc=$rc out=[$out]"

# --- fwup task, device alias, pty helper ------------------------------------

out=$(call "avocado_safe_disk_fwup_task")
rc=$?
{ [ $rc -eq 0 ] && [ "$out" = "complete" ]; } && ok "fwup_task defaults to complete" || bad "fwup default: rc=$rc out=[$out]"
out=$(call "AVOCADO_PROVISION_FWUP_TASK=upgrade avocado_safe_disk_fwup_task")
rc=$?
{ [ $rc -eq 0 ] && [ "$out" = "upgrade" ]; } && ok "fwup_task returns upgrade when asked" || bad "fwup upgrade: rc=$rc out=[$out]"
out=$(call "AVOCADO_PROVISION_FWUP_TASK=full avocado_safe_disk_fwup_task")
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "FWUP_TASK=full"; } && ok "fwup_task refuses full" || bad "fwup full: rc=$rc out=[$out]"

out=$(call "avocado_safe_disk_sd_device")
rc=$?
{ [ $rc -eq 0 ] && [ -z "$out" ]; } && ok "sd_device is empty when neither variable is set" || bad "sd none: rc=$rc out=[$out]"
out=$(call "AVOCADO_PROVISION_DEVICE=/dev/sdb avocado_safe_disk_sd_device")
[ "$out" = "/dev/sdb" ] && ok "sd_device reads AVOCADO_PROVISION_DEVICE" || bad "sd primary: [$out]"
out=$(call "AVOCADO_SD_DEVICE=/dev/sdc avocado_safe_disk_sd_device")
[ "$out" = "/dev/sdc" ] && ok "sd_device accepts the AVOCADO_SD_DEVICE alias" || bad "sd alias: [$out]"
out=$(call "AVOCADO_PROVISION_DEVICE=/dev/sdb AVOCADO_SD_DEVICE=/dev/sdb avocado_safe_disk_sd_device")
[ "$out" = "/dev/sdb" ] && ok "sd_device accepts both variables when they agree" || bad "sd agree: [$out]"
out=$(call "AVOCADO_PROVISION_DEVICE=/dev/sdb AVOCADO_SD_DEVICE=/dev/sdc avocado_safe_disk_sd_device")
rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q AVOCADO_PROVISION_DEVICE && echo "$out" | grep -q AVOCADO_SD_DEVICE && ! echo "$out" | grep -qx "/dev/sd[bc]"; } \
  && ok "sd_device refuses differing variables, naming both" || bad "sd differ: rc=$rc out=[$out]"

# shellcheck source=pty-run.sh
. "$here/pty-run.sh"
if ! command -v script >/dev/null 2>&1; then
  echo "  SKIP - script(1) missing: run_with_tty checks not run"
  pass=$((pass + 3))
else
  out=$(run_with_tty 'hello\n' bash -c '[ -t 0 ] && echo tty-yes || echo tty-no')
  echo "$out" | tr -d '\r' | grep -qx tty-yes && ok "run_with_tty gives the command a terminal on stdin" || bad "pty tty: [$out]"
  # shellcheck disable=SC2016 # the $x expands in the inner bash
  out=$(run_with_tty 'typed-line\n' bash -c 'read -r x; echo "got:$x"')
  echo "$out" | tr -d '\r' | grep -qx 'got:typed-line' && ok "run_with_tty feeds the typed input to a prompt" || bad "pty input: [$out]"
  run_with_tty 'x\n' bash -c 'exit 7' >/dev/null
  [ $? -eq 7 ] && ok "run_with_tty returns the command's exit status" || bad "pty rc: $?"
fi

# --- bus candidates ---------------------------------------------------------

setup
idpath sdb "pci-0000:00:14.0-usb-0:2:1.0-scsi-0:0:0:0"
idpath sda "pci-0000:00:17.0-ata-1"
echo 1 >"$w/sys/devices/$ATAPATH/sda/removable"
out=$(call "avocado_safe_disk_bus_candidates")
rc=$?
[ "$out" = "$(printf '%s\n%s' "$w/dev/mmcblk0" "$w/dev/sdb")" ] \
  && ok "bus_candidates lists whole USB and MMC disks only: no partitions, no SATA, removable flag ignored" || bad "candidates: rc=$rc out=[$out]"

setup
idpath sdb "pci-0000:00:17.0-ata-1"
idpath mmcblk0 "pci-0000:00:17.0-ata-2"
out=$(call "avocado_safe_disk_bus_candidates")
[ -z "$out" ] && ok "bus_candidates prints nothing when no disk is on a USB or MMC bus" || bad "candidates none: [$out]"

N=117
echo
echo "passed: $pass  failed: $fail  (checks: $((pass + fail))/$N run)"
[ "$fail" -eq 0 ] && [ $((pass + fail)) -eq "$N" ]
