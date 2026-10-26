#!/bin/sh
# Host test for avocado-on-root-disk against a fake sysfs holding two Avocado
# disks with the same partition labels (an eMMC and a microSD).
# Run: sh meta-avocado-distro/recipes-core/base-files/tests/test-avocado-on-root-disk.sh
set -u
here=$(cd "$(dirname "$0")" && pwd)
helper="$here/../files/avocado-on-root-disk"
w=$(mktemp -d)
trap 'rm -rf "$w"' EXIT
fail=0

# disk <name> <rootfs-a PARTUUID> <var PARTUUID>
disk() {
  mkdir -p "$w/sys/class/block"
  for n in 3 5; do
    mkdir -p "$w/sys/block/$1/$1p$n"
    ln -s "../../block/$1/$1p$n" "$w/sys/class/block/$1p$n"
  done
  printf 'DEVTYPE=partition\nPARTN=3\nPARTNAME=rootfs-a\nPARTUUID=%s\n' "$2" >"$w/sys/block/$1/$1p3/uevent"
  printf 'DEVTYPE=partition\nPARTN=5\nPARTNAME=var\nPARTUUID=%s\n' "$3" >"$w/sys/block/$1/$1p5/uevent"
}
disk mmcblk0 489ee3a6-ca13-4f67-913a-5eea91ff9b03 aaaaaaaa-0000-0000-0000-000000000000
disk mmcblk1 bae4e9cc-4f05-475d-afae-be1c6a262c66 bbbbbbbb-0000-0000-0000-000000000000

# expect <0|1> <partition> <cmdline> <description>
expect() {
  printf '%s\n' "$3" >"$w/cmdline"
  AVOCADO_SYSFS="$w/sys" AVOCADO_CMDLINE="$w/cmdline" sh "$helper" "$2"
  got=$?
  if [ "$got" = "$1" ]; then echo "ok - $4"; else echo "FAIL - $4 (exit $got, want $1)"; fail=1; fi
}

emmc_root="root=PARTUUID=BAE4E9CC-4F05-475D-AFAE-BE1C6A262C66 rootwait ro"
expect 0 mmcblk1p5 "$emmc_root" "eMMC root: the eMMC's var is on the root disk (PARTUUID case-folded)"
expect 1 mmcblk0p5 "$emmc_root" "eMMC root: the microSD's var is not"
sd_root="console=ttyS2 root=PARTUUID=489ee3a6-ca13-4f67-913a-5eea91ff9b03"
expect 0 mmcblk0p5 "$sd_root" "microSD root: the microSD's var is on the root disk"
expect 1 mmcblk1p5 "$sd_root" "microSD root: the eMMC's var is not"
expect 0 mmcblk0p5 "root=PARTLABEL=rootfs-a rootwait" "root=PARTLABEL: no disk to scope to, every var passes (unchanged behaviour)"
expect 0 mmcblk1p5 "root=/dev/mmcblk1p3 rootwait" "root=/dev node: every var passes (unchanged behaviour)"
expect 1 mmcblk1p5 "root=PARTUUID=00000000-0000-0000-0000-000000000000" "a root PARTUUID on neither disk: no var is claimed"

exit $fail
