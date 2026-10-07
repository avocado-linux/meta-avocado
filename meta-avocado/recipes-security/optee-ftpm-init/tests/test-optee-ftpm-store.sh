#!/usr/bin/env bash
# Host test with a fake /sys: the fTPM store is resolved on the boot disk only,
# never from another disk that carries the same partition label.
set -u
here=$(cd "$(dirname "$0")" && pwd); script=$here/../files/optee-ftpm-setup.sh
w=$(mktemp -d); trap 'rm -rf "$w"' EXIT
pass=0; fail=0; ok(){ echo "  ok   - $1"; pass=$((pass+1)); }; bad(){ echo "  FAIL - $1"; fail=$((fail+1)); }
part(){ mkdir -p "$w/sys/block/$1/$2"; printf 'DEVNAME=%s\nPARTNAME=%s\n' "$2" "$3" > "$w/sys/block/$1/$2/uevent"; }
part mmcblk0 mmcblk0p1 APP; part mmcblk0 mmcblk0p15 reserved
part nvme0n1 nvme0n1p1 APP; part nvme0n1 nvme0n1p15 reserved; part nvme0n1 nvme0n1p14 reserved_b
part sda sda1 data
res(){ OPTEE_FTPM_SETUP_LIB=1 AVOCADO_SYSFS="$w/sys" bash -c '. "$1"; store_on_disk "$2" "$3"' _ "$script" "$1" "$2"; }

[ "$(res mmcblk0 /dev/disk/by-partlabel/reserved)" = /dev/mmcblk0p15 ] && ok "eMMC boot takes the eMMC store" || bad "emmc: $(res mmcblk0 /dev/disk/by-partlabel/reserved)"
[ "$(res nvme0n1 /dev/disk/by-partlabel/reserved)" = /dev/nvme0n1p15 ] && ok "NVMe boot takes the NVMe store, not reserved_b" || bad "nvme: $(res nvme0n1 /dev/disk/by-partlabel/reserved)"
[ -z "$(res sda /dev/disk/by-partlabel/reserved)" ] && ok "a boot disk without the label resolves to nothing, not another disk" || bad "sda: $(res sda /dev/disk/by-partlabel/reserved)"
[ -z "$(res nvme1n1 /dev/disk/by-partlabel/reserved)" ] && ok "an unknown disk resolves to nothing" || bad "unknown"

echo "$pass passed, $fail failed"; [ $fail -eq 0 ]
