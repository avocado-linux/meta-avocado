#!/usr/bin/env bash
#
# The swupdate pre-install handler must resolve the OTA target slot on the
# booted disk only, from sysfs PARTNAME, and refuse rather than guess.
#
# Lifts log, partname_of and resolve_partlabel_on_disk out of rootfs-pre.sh and
# runs them against a fake /sys/block holding two disks that both carry APP and
# APP_b - the layout that made the target ambiguous in the first place.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$SCRIPT_DIR/../../../recipes-core/swupdate/swupdate/rootfs-pre.sh"
failures=0

pass() { printf '  ok   %s\n' "$1"; }
fail() {
  printf '  FAIL %s\n' "$1"
  failures=$((failures + 1))
}

[ -f "$TARGET" ] || {
  echo "target script not found: $TARGET" >&2
  exit 1
}

echo "test-ota-target-resolve: $TARGET"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

for fn in log partname_of resolve_partlabel_on_disk; do
  awk -v fn="$fn" '$0 ~ "^"fn"\\(\\) \\{"{f=1} f{print} f&&/^\}$/{exit}' \
    "$TARGET" >>"$work/fn.sh"
done

# Point the lifted code at the fake tree. Device nodes cannot be faked, so the
# block-device test becomes an existence test on a fake /dev.
# shellcheck disable=SC2016  # $cand is matched literally in the script text
sed -i -e "s|/sys/block|$work/sys/block|g" \
  -e "s|\"/dev/\$(basename|\"$work/dev/\$(basename|" \
  -e 's|\[ ! -b "\$cand" \]|[ ! -e "$cand" ]|' "$work/fn.sh"
# shellcheck disable=SC2016  # literal script text, not an expansion
for want in "$work/sys/block" "$work/dev/" '! -e "$cand"'; do
  grep -qF "$want" "$work/fn.sh" || {
    fail "rewrite did not land: $want"
    exit 1
  }
done

# part <disk> <partition> <PARTNAME>
part() {
  mkdir -p "$work/sys/block/$1/$2" "$work/dev"
  printf 'MAJOR=259\nDEVNAME=%s\nDEVTYPE=partition\nPARTNAME=%s\n' "$2" "$3" \
    >"$work/sys/block/$1/$2/uevent"
  : >"$work/dev/$2"
}
part nvme0n1 nvme0n1p1 APP
part nvme0n1 nvme0n1p2 APP_b
part mmcblk0 mmcblk0p1 APP
part mmcblk0 mmcblk0p2 APP_b
# The next namespace: a sibling of nvme0n1 in sysfs, never a child of it.
part nvme0n11 nvme0n11p2 APP_b

# resolve <label> <disk> -> sets out, rc. Captured the way the caller captures
# it, so anything the function logs to stdout lands in $out.
resolve() {
  out=$(LOGFILE="$work/log" bash -c '. "$1"; resolve_partlabel_on_disk "$2" "$3"' \
    _ "$work/fn.sh" "$1" "$2" 2>/dev/null)
  rc=$?
}

resolve APP_b /dev/nvme0n1
if [ "$rc" -eq 0 ] && [ "$out" = "$work/dev/nvme0n1p2" ]; then
  pass "APP_b on the booted NVMe resolves to nvme0n1p2"
else
  fail "APP_b on nvme0n1: rc=$rc out=[$out]"
fi

resolve APP_b /dev/mmcblk0
if [ "$rc" -eq 0 ] && [ "$out" = "$work/dev/mmcblk0p2" ]; then
  pass "the same label on the SD resolves to the SD, not the NVMe"
else
  fail "APP_b on mmcblk0: rc=$rc out=[$out]"
fi

resolve APP_x /dev/nvme0n1
if [ "$rc" -ne 0 ] && [ -z "$out" ]; then
  pass "an unknown label refuses with nothing captured"
else
  fail "unknown label: rc=$rc out=[$out]"
fi

resolve APP_b /dev/nvme9n9
if [ "$rc" -ne 0 ] && [ -z "$out" ]; then
  pass "a disk with no sysfs directory refuses"
else
  fail "missing disk: rc=$rc out=[$out]"
fi

# Two partitions on the booted disk carrying the target label. The refusal
# logs a line; with log() on stdout that line was captured as the device and
# the update went ahead.
part nvme0n1 nvme0n1p3 APP_b
resolve APP_b /dev/nvme0n1
if [ -z "$out" ]; then
  pass "an ambiguous label refuses, and the refusal is not captured as a device"
else
  fail "ambiguous label captured [$out] (rc=$rc); the caller would write there"
fi

echo
if [ "$failures" -eq 0 ]; then
  echo "test-ota-target-resolve: PASS"
  exit 0
fi
echo "test-ota-target-resolve: FAIL ($failures)"
exit 1
