#!/usr/bin/env bash
#
# avocado-tegra-esp-generator must point boot-efi.mount at the ESP on the disk
# the system booted from. When the booted disk has no single esp it leaves the
# unit as shipped (exit 0, no drop-in) if at most one disk has an esp, and writes
# a drop-in that skips the mount if more than one does. It always exits 0.
#
# Runs the real generator against a fake /proc/mounts, /sys/block and /dev. The
# layout is the one that made the shipped PARTLABEL lookup wrong: an NVMe and an
# SD card that both carry `esp` at p11 and `esp_alt` at p14.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$SCRIPT_DIR/../../../recipes-core/systemd/files/avocado-tegra-esp-generator"
failures=0
checks=0

pass() {
  checks=$((checks + 1))
  printf '  ok   %s\n' "$1"
}
fail() {
  checks=$((checks + 1))
  printf '  FAIL %s\n' "$1"
  failures=$((failures + 1))
}

[ -f "$TARGET" ] || {
  echo "target script not found: $TARGET" >&2
  exit 1
}

echo "test-esp-generator: $TARGET"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Point the script at the fake tree. Device nodes cannot be faked, so the
# block-device test becomes an existence test on a fake /dev. The /dev/ prefix in
# the root-device case patterns is left alone: those match the value read from
# the fake /proc/mounts, which keeps the real names.
# shellcheck disable=SC2016  # $candidate and $(basename are matched literally
sed -e "s|/proc/mounts|$work/mounts|g" \
  -e "s|/sys/block|$work/sys/block|g" \
  -e "s|\"/dev/\$(basename|\"$work/dev/\$(basename|" \
  -e 's|\[ -b "\$candidate" \]|[ -e "$candidate" ]|' \
  "$TARGET" >"$work/gen.sh"
# shellcheck disable=SC2016  # literal script text, not an expansion
for want in "$work/mounts" "$work/sys/block" "$work/dev/" '-e "$candidate"'; do
  grep -qF -- "$want" "$work/gen.sh" || {
    echo "  FAIL rewrite did not land: $want"
    exit 1
  }
done

# part <disk> <partition> <PARTNAME> [nodev]
part() {
  mkdir -p "$work/sys/block/$1/$2" "$work/dev"
  printf 'MAJOR=259\nDEVNAME=%s\nDEVTYPE=partition\nPARTNAME=%s\n' "$2" "$3" \
    >"$work/sys/block/$1/$2/uevent"
  [ "${4:-}" = nodev ] || : >"$work/dev/$2"
}

# Both disks provisioned the way the bench board is.
part nvme0n1 nvme0n1p1 APP
part nvme0n1 nvme0n1p11 esp
part nvme0n1 nvme0n1p14 esp_alt
part mmcblk0 mmcblk0p1 APP
part mmcblk0 mmcblk0p11 esp
part mmcblk0 mmcblk0p14 esp_alt

# run <root-device-or-empty> -> sets rc, err, and $out_dir. An empty argument
# leaves /proc/mounts without a root entry.
run() {
  out_dir="$work/out"
  rm -rf "$out_dir"
  mkdir -p "$out_dir"
  if [ -n "$1" ]; then
    printf '%s / ext4 rw 0 0\nproc /proc proc rw 0 0\n' "$1" >"$work/mounts"
  else
    printf 'proc /proc proc rw 0 0\n' >"$work/mounts"
  fi
  err=$(sh "$work/gen.sh" "$out_dir" 2>&1 >/dev/null)
  rc=$?
}

dropin="boot-efi.mount.d/10-avocado-booted-disk.conf"

run /dev/nvme0n1p1
if [ "$rc" -eq 0 ] && [ "$(grep '^What=' "$out_dir/$dropin" 2>/dev/null)" = "What=$work/dev/nvme0n1p11" ]; then
  pass "booted from NVMe with an SD installed, the NVMe ESP is chosen"
else
  fail "NVMe boot: rc=$rc What=[$(grep '^What=' "$out_dir/$dropin" 2>/dev/null)]"
fi

run /dev/mmcblk0p1
if [ "$rc" -eq 0 ] && [ "$(grep '^What=' "$out_dir/$dropin" 2>/dev/null)" = "What=$work/dev/mmcblk0p11" ]; then
  pass "booted from SD, the SD ESP is chosen rather than the NVMe's"
else
  fail "SD boot: rc=$rc What=[$(grep '^What=' "$out_dir/$dropin" 2>/dev/null)]"
fi

if [ "$(grep -c '^What=' "$out_dir/$dropin" 2>/dev/null)" = 1 ] && grep -q '^\[Mount\]$' "$out_dir/$dropin"; then
  pass "the drop-in is a single What= under [Mount]"
else
  fail "drop-in shape: $(cat "$out_dir/$dropin" 2>/dev/null)"
fi

# esp_alt must never be taken for the ESP: the match is on the exact name.
if ! grep -q 'p14' "$out_dir/$dropin"; then
  pass "esp_alt is not mistaken for esp"
else
  fail "esp_alt chosen: $(grep '^What=' "$out_dir/$dropin")"
fi

# The cases below each start from an empty tree: the policy counts esp across
# every disk, so a disk left over from an earlier case would change the answer.
reset_tree() {
  rm -rf "${work:?}/sys" "${work:?}/dev"
  mkdir -p "$work/sys/block" "$work/dev"
}

# Result helpers for the two non-pinning outcomes.
shipped() { [ "$rc" -eq 0 ] && [ ! -e "$out_dir/boot-efi.mount.d" ]; }
skipped() {
  [ "$rc" -eq 0 ] &&
    [ "$(grep -c '^ConditionPathExists=/run/avocado-esp-unresolved$' "$out_dir/$dropin" 2>/dev/null)" = 1 ] &&
    grep -q '^\[Unit\]$' "$out_dir/$dropin" &&
    ! grep -q '^What=' "$out_dir/$dropin"
}
state() { [ -e "$out_dir/boot-efi.mount.d" ] && echo dropin-present || echo dropin-absent; }

# No esp on any disk: the shipped unit cannot be ambiguous, leave it.
reset_tree
part sda sda1 APP
run /dev/sda1
if shipped && printf '%s' "$err" | grep -q 'leaving boot-efi.mount as shipped'; then
  pass "no esp on any disk leaves the unit as shipped and exits 0"
else
  fail "no esp anywhere: rc=$rc $(state) err=[$err]"
fi

# One esp, on a disk that did not boot: it is the only one, so the shipped label
# cannot point elsewhere. It is not borrowed as the booted disk's ESP either.
reset_tree
part sda sda1 APP
part sdc sdc1 esp
run /dev/sda1
if shipped && ! grep -rq 'sdc1' "$out_dir" 2>/dev/null; then
  pass "a single esp on another disk is left to the shipped unit, not borrowed"
else
  fail "esp on other disk only: rc=$rc $(state)"
fi

# The booted disk has no esp and two other disks each carry one: by-partlabel/esp
# could resolve to either, so the mount is skipped.
reset_tree
part sda sda1 APP
part sdb sdb1 esp
part sdc sdc1 esp
run /dev/sda1
if skipped && printf '%s' "$err" | grep -q 'boot-efi.mount skipped'; then
  pass "no esp on the booted disk and one on each of two others skips the mount"
else
  fail "two other disks: rc=$rc err=[$err] dropin=$(cat "$out_dir/$dropin" 2>/dev/null)"
fi

# Two esp on the booted disk is an ambiguous layout: refuse rather than pick.
reset_tree
part sdb sdb1 APP
part sdb sdb2 esp
part sdb sdb3 esp
run /dev/sdb1
if skipped; then
  pass "two esp on the booted disk skips the mount and exits 0"
else
  fail "ambiguous: rc=$rc err=[$err] dropin=$(cat "$out_dir/$dropin" 2>/dev/null)"
fi

# The booted disk's single esp wins even when another disk carries one too: the
# pinned What= is the whole point of the generator.
reset_tree
part sda sda1 APP
part sda sda2 esp
part sdb sdb1 esp
run /dev/sda1
if [ "$rc" -eq 0 ] && [ "$(grep '^What=' "$out_dir/$dropin" 2>/dev/null)" = "What=$work/dev/sda2" ] &&
  ! grep -q '^ConditionPathExists=' "$out_dir/$dropin"; then
  pass "one esp on the booted disk is pinned even with another disk's esp present"
else
  fail "pin with other disk: rc=$rc dropin=$(cat "$out_dir/$dropin" 2>/dev/null)"
fi

# nvme0n11 is a sibling namespace of nvme0n1 in sysfs, never a child. Its esp
# must not be found by a prefix match on the disk name.
reset_tree
part nvme1n1 nvme1n1p1 APP
part nvme1n11 nvme1n11p11 esp
run /dev/nvme1n1p1
if shipped; then
  pass "a sibling namespace's esp is not taken for this disk's"
else
  fail "sibling namespace: rc=$rc $(state)"
fi

# An esp present in sysfs with no device node is skipped, not written down.
reset_tree
part vda vda1 APP
part vda vda2 esp nodev
run /dev/vda1
if shipped; then
  pass "an esp with no block device node is skipped"
else
  fail "no node: rc=$rc $(state)"
fi

# Root on something that is not a partition of a disk this knows (device-mapper,
# overlay, a missing entry): leave the unit alone.
for root in /dev/dm-0 overlay ""; do
  run "$root"
  if [ "$rc" -eq 0 ] && [ ! -e "$out_dir/boot-efi.mount.d" ]; then
    pass "root device [${root:-none}] leaves the unit as shipped"
  else
    fail "root [${root:-none}]: rc=$rc dropin=$([ -e "$out_dir/boot-efi.mount.d" ] && echo present || echo absent)"
  fi
done

# Root names a disk that has no sysfs directory.
run /dev/nvme9n9p1
if [ "$rc" -eq 0 ] && [ ! -e "$out_dir/boot-efi.mount.d" ]; then
  pass "a root disk with no sysfs directory leaves the unit as shipped"
else
  fail "missing disk: rc=$rc dropin=$([ -e "$out_dir/boot-efi.mount.d" ] && echo present || echo absent)"
fi

# Called with no output directory, as a bare invocation would be.
printf '/dev/nvme0n1p1 / ext4 rw 0 0\n' >"$work/mounts"
(
  cd "$work" || exit 1
  sh "$work/gen.sh" >/dev/null 2>&1
)
rc=$?
if [ "$rc" -eq 0 ] && [ -z "$(find "$work" -maxdepth 1 -name 'boot-efi.mount.d' 2>/dev/null)" ]; then
  pass "no output directory argument exits 0 and writes nothing"
else
  fail "no argument: rc=$rc"
fi

echo
# A case that is skipped or exits the script early would otherwise read as a
# pass; the count is what says every case ran.
expected_checks=16
echo "checks: $checks/$expected_checks run"
if [ "$checks" -ne "$expected_checks" ]; then
  echo "test-esp-generator: FAIL (ran $checks of $expected_checks checks)"
  exit 1
fi
if [ "$failures" -eq 0 ]; then
  echo "test-esp-generator: PASS"
  exit 0
fi
echo "test-esp-generator: FAIL ($failures)"
exit 1
