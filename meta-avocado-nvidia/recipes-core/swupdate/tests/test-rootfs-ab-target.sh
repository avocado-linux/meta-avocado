#!/usr/bin/env bash
#
# The Tegra A/B swupdate scripts must write the inactive slot on the disk the
# running rootfs lives on, not the first disk carrying the label.
#
# A board with a provisioned SD card and a provisioned NVMe has APP and APP_b
# on both. Booted from the NVMe, a by-partlabel lookup can name the SD card's
# APP_b, so the update lands on a disk the next boot never reads, and the
# post-install then switches the slot anyway.
#
# This runs the real rootfs-pre.sh and rootfs-post.sh with /proc/self/mountinfo,
# /sys, /dev and /tmp pointed into a scratch tree and nvbootctrl, udevadm,
# blkid and findmnt stubbed, then checks which device the pre-install chose
# and whether the post-install switched the slot. The scratch /dev holds
# regular files, so the scripts' block-device tests are relaxed to -e.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${SWUPDATE_SCRIPTS:-$SCRIPT_DIR/../swupdate}"
failures=0

pass() { printf '  ok   %s\n' "$1"; }
fail() {
  printf '  FAIL %s\n' "$1"
  failures=$((failures + 1))
}

for f in "$SRC/rootfs-pre.sh" "$SRC/rootfs-post.sh"; do
  [ -f "$f" ] || {
    echo "script not found: $f" >&2
    exit 1
  }
done

echo "test-rootfs-ab-target: $SRC"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
R="$work/root"

mkdir -p "$work/bin"
cat > "$work/bin/nvbootctrl" <<'EOF'
#!/bin/sh
case "$*" in
  *get-current-slot*) echo "$SLOT" ;;
  *set-active-boot-slot*) echo "$*" >> "$NVBOOTCTRL_LOG" ;;
esac
EOF
printf '#!/bin/sh\nexit 0\n' > "$work/bin/udevadm"
printf '#!/bin/sh\nexit 0\n' > "$work/bin/blkid"
# findmnt reports nothing mounted, except that "-n -S <dev>" succeeds for the
# device whose basename is $MOUNTED.
cat > "$work/bin/findmnt" <<'EOF'
#!/bin/sh
[ -n "${MOUNTED:-}" ] && [ "$1 $2" = "-n -S" ] && [ "${3##*/}" = "$MOUNTED" ] && exit 0
exit 1
EOF
chmod +x "$work/bin/"*

# SWUpdate runs each script on its own, so the helpers are carried in both.
# A fix applied to one copy only must fail here.
for fn in booted_root_part parts_labelled only_one; do
  a=$(sed -n "/^$fn() {/,/^}/p" "$SRC/rootfs-pre.sh")
  b=$(sed -n "/^$fn() {/,/^}/p" "$SRC/rootfs-post.sh")
  if [ -n "$a" ] && [ "$a" = "$b" ]; then
    pass "$fn is the same in rootfs-pre.sh and rootfs-post.sh"
  else
    fail "$fn differs between rootfs-pre.sh and rootfs-post.sh (or is missing)"
  fi
done

# /tmp/ goes first: $R lives under /tmp, and sed applies each expression to
# the output of the one before. /dev/ is rewritten only where a path starts,
# so /sys/dev/block keeps its shape.
for s in rootfs-pre.sh rootfs-post.sh; do
  sed -e "s,/tmp/,$R/tmp/,g" \
    -e "s,\([\" ]\)/dev/,\1$R/dev/,g" \
    -e "s,/proc/self/mountinfo,$R/proc/self/mountinfo,g" \
    -e "s,/sys/,$R/sys/,g" \
    -e 's/\[ \(! \)\{0,1\}-b /[ \1-e /g' \
    "$SRC/$s" > "$work/$s"
done

# disk <controller> <disk> <part>=<label>:<maj:min> ...
disk() {
  local ctrl=$1 d=$2 p name label mm dir
  shift 2
  dir="$R/sys/devices/platform/$ctrl/$d"
  mkdir -p "$dir"
  ln -s "$dir" "$R/sys/block/$d"
  for p in "$@"; do
    name=${p%%=*}
    label=${p#*=}
    mm=${label#*:}
    label=${label%%:*}
    mkdir -p "$dir/$name"
    : > "$dir/$name/partition"
    printf 'MAJOR=%s\nMINOR=%s\nDEVNAME=%s\nDEVTYPE=partition\nPARTNAME=%s\n' \
      "${mm%:*}" "${mm#*:}" "$name" "$label" > "$dir/$name/uevent"
    ln -s "$dir/$name" "$R/sys/class/block/$name"
    ln -s "$dir/$name" "$R/sys/dev/block/$mm"
    : > "$R/dev/$name"
    # udev keeps one by-partlabel link per label; the first disk set up wins.
    [ -e "$R/dev/disk/by-partlabel/$label" ] ||
      ln -s "$R/dev/$name" "$R/dev/disk/by-partlabel/$label"
  done
}

fresh() {
  rm -rf "$R"
  mkdir -p "$R/proc/self" "$R/sys/block" "$R/sys/class/block" "$R/sys/dev/block" "$R/dev/disk/by-partlabel" "$R/tmp"
}

# / mounted from <maj:min>; with several, one mountinfo line each, in order,
# the last one being what / is now.
root_on() {
  local mm
  : > "$R/proc/self/mountinfo"
  for mm in "$@"; do
    printf '22 1 %s / / ro,relatime shared:1 - squashfs /dev/x ro\n' "$mm" >> "$R/proc/self/mountinfo"
  done
}

two_disks() {
  disk 3400000.mmc mmcblk0 mmcblk0p1=APP:179:1 mmcblk0p2=APP_b:179:2
  disk 14160000.pcie nvme0n1 nvme0n1p1=APP:259:1 nvme0n1p2=APP_b:259:2
}

# Sets pre_rc, post_rc, target (basename the pre-install chose), switched.
run() {
  : > "$work/nvbootctrl.log"
  local env=(PATH="$work/bin:$PATH" SLOT="${SLOT:-0}" NVBOOTCTRL_LOG="$work/nvbootctrl.log" MOUNTED="${MOUNTED:-}")
  pre_out=$(env "${env[@]}" sh "$work/rootfs-pre.sh" 2>&1)
  pre_rc=$?
  target=$(sed -n 's/^TEGRA_TARGET_DEV=//p' "$R/tmp/tegra-ab-vars" 2>/dev/null)
  target=${target##*/}
  if [ -n "${FORGE_TARGET:-}" ] && [ -f "$R/tmp/tegra-ab-vars" ]; then
    sed -i "s,^TEGRA_TARGET_DEV=.*,TEGRA_TARGET_DEV=$R/dev/$FORGE_TARGET," "$R/tmp/tegra-ab-vars"
  fi
  post_out=$(env "${env[@]}" sh "$work/rootfs-post.sh" 2>&1)
  post_rc=$?
  switched=$(cat "$work/nvbootctrl.log")
}

fresh
two_disks
root_on 259:1
run
if [ "$pre_rc" -eq 0 ] && [ "$target" = "nvme0n1p2" ] && [ "$post_rc" -eq 0 ] && [ -n "$switched" ]; then
  pass "booted from NVMe with both disks labelled, APP_b on the NVMe is written"
else
  fail "booted NVMe: target '$target' pre=$pre_rc post=$post_rc: $(echo "$pre_out$post_out" | grep ERROR | head -2)"
fi

fresh
two_disks
root_on 179:1
run
if [ "$pre_rc" -eq 0 ] && [ "$target" = "mmcblk0p2" ] && [ "$post_rc" -eq 0 ]; then
  pass "booted from SD with both disks labelled, APP_b on the SD card is written"
else
  fail "booted SD: target '$target' pre=$pre_rc post=$post_rc"
fi

fresh
two_disks
root_on 259:2
SLOT=1 run
if [ "$pre_rc" -eq 0 ] && [ "$target" = "nvme0n1p1" ] && [ "$post_rc" -eq 0 ]; then
  pass "slot B running from NVMe writes APP on the NVMe"
else
  fail "slot B on NVMe: target '$target' pre=$pre_rc post=$post_rc"
fi

# / on a dm device (dm-verity, dm-crypt) backed by the NVMe partition.
fresh
two_disks
mkdir -p "$R/sys/devices/virtual/block/dm-0/slaves"
ln -s "$R/sys/devices/platform/14160000.pcie/nvme0n1/nvme0n1p1" "$R/sys/devices/virtual/block/dm-0/slaves/nvme0n1p1"
ln -s "$R/sys/devices/virtual/block/dm-0" "$R/sys/dev/block/252:0"
root_on 252:0
run
if [ "$pre_rc" -eq 0 ] && [ "$target" = "nvme0n1p2" ] && [ "$post_rc" -eq 0 ]; then
  pass "a device-mapper root is followed to the NVMe it sits on"
else
  fail "dm root: target '$target' pre=$pre_rc post=$post_rc"
fi

# / is an overlay with no block device: one disk carrying the label is safe.
fresh
disk 14160000.pcie nvme0n1 nvme0n1p1=APP:259:1 nvme0n1p2=APP_b:259:2
root_on 0:30
run
if [ "$pre_rc" -eq 0 ] && [ "$target" = "nvme0n1p2" ] && [ "$post_rc" -eq 0 ] &&
  echo "$pre_out" | grep -q "cannot tell which disk"; then
  pass "with the booted disk unknown, a unique label is used, with a warning"
else
  fail "unknown disk, unique label: target '$target' pre=$pre_rc post=$post_rc"
fi

# ... and two disks carrying it is a guess, so nothing is written.
fresh
two_disks
root_on 0:30
run
if [ "$pre_rc" -ne 0 ] && [ -z "$target" ] && [ ! -e "$R/tmp/target_rootfs" ] && [ -z "$switched" ]; then
  pass "with the booted disk unknown and the label on two disks, the update refuses"
else
  fail "unknown disk, duplicate label: target '$target' pre=$pre_rc switched='$switched'"
fi

# The booted disk has no APP_b: never fall over to the other disk's.
fresh
disk 3400000.mmc mmcblk0 mmcblk0p1=APP:179:1 mmcblk0p2=APP_b:179:2
disk 14160000.pcie nvme0n1 nvme0n1p1=APP:259:1
root_on 259:1
run
if [ "$pre_rc" -ne 0 ] && [ -z "$target" ] && [ -z "$switched" ]; then
  pass "a booted disk with no target slot refuses instead of using another disk's"
else
  fail "booted disk lacks APP_b: target '$target' pre=$pre_rc switched='$switched'"
fi

# The post-install is handed a target on the other disk: it must not switch.
fresh
two_disks
root_on 259:1
FORGE_TARGET=mmcblk0p2 run
if [ "$pre_rc" -eq 0 ] && [ "$post_rc" -ne 0 ] && [ -z "$switched" ] &&
  echo "$post_out" | grep -q "Not switching the boot slot"; then
  pass "the post-install refuses to switch the slot for a target on another disk"
else
  fail "post cross-disk: post=$post_rc switched='$switched'"
fi

# Booted disk unknown, APP_b only on the SD card, APP on both disks. The
# target label is unique but the active one is not, so there are two installs
# and the one written would be picked by layout, not by which disk booted.
fresh
disk 3400000.mmc mmcblk0 mmcblk0p1=APP:179:1 mmcblk0p2=APP_b:179:2
disk 14160000.pcie nvme0n1 nvme0n1p1=APP:259:1
root_on 0:30
run
if [ "$pre_rc" -ne 0 ] && [ -z "$target" ] && [ ! -e "$R/tmp/target_rootfs" ] && [ -z "$switched" ] &&
  echo "$pre_out" | grep -q "need exactly one partition labelled 'APP'"; then
  pass "with the booted disk unknown and the active label on two disks, the update refuses"
else
  fail "unknown disk, duplicate active label: target '$target' pre=$pre_rc switched='$switched'"
fi

# The same layout reaching the post-install directly, as a pre-install that
# predates the check would leave it: the post-install must not switch either.
fresh
disk 3400000.mmc mmcblk0 mmcblk0p1=APP:179:1 mmcblk0p2=APP_b:179:2
disk 14160000.pcie nvme0n1 nvme0n1p1=APP:259:1
root_on 0:30
printf 'TEGRA_INACTIVE_SLOT=1\nTEGRA_TARGET_DEV=%s\nTEGRA_TARGET_PARTLABEL=APP_b\nTEGRA_ACTIVE_PARTLABEL=APP\n' \
  "$R/dev/mmcblk0p2" > "$R/tmp/tegra-ab-vars"
: > "$work/nvbootctrl.log"
post_out=$(env PATH="$work/bin:$PATH" SLOT=0 NVBOOTCTRL_LOG="$work/nvbootctrl.log" sh "$work/rootfs-post.sh" 2>&1)
post_rc=$?
switched=$(cat "$work/nvbootctrl.log")
if [ "$post_rc" -ne 0 ] && [ -z "$switched" ] && echo "$post_out" | grep -q "Not switching the boot slot"; then
  pass "the post-install refuses to switch when the active label is on two disks"
else
  fail "post, duplicate active label: post=$post_rc switched='$switched'"
fi

# nvbootctrl says slot 0, but / is APP_b: the target resolves to the running
# rootfs, and writing it would overwrite the system in use.
fresh
two_disks
root_on 259:2
run
if [ "$pre_rc" -ne 0 ] && [ -z "$target" ] && [ -z "$switched" ] &&
  echo "$pre_out" | grep -q "matches active device"; then
  pass "a target that is the running rootfs refuses"
else
  fail "target == active: target '$target' pre=$pre_rc switched='$switched'"
fi

# The target partition is mounted somewhere: refuse rather than write under it.
fresh
two_disks
root_on 259:1
MOUNTED=nvme0n1p2 run
if [ "$pre_rc" -ne 0 ] && [ -z "$target" ] && [ -z "$switched" ] &&
  echo "$pre_out" | grep -q "appears to be mounted"; then
  pass "a mounted target refuses"
else
  fail "mounted target: target '$target' pre=$pre_rc switched='$switched'"
fi

# / on a dm device over two partitions on different disks. booted_root_part
# follows a dm root only through a single slave: with several, no one disk
# booted, so it reports the disk unknown and the label rule applies, which
# refuses here because both disks carry both labels. Following either slave
# would write that slave's disk.
fresh
two_disks
mkdir -p "$R/sys/devices/virtual/block/dm-0/slaves"
ln -s "$R/sys/devices/platform/3400000.mmc/mmcblk0/mmcblk0p1" "$R/sys/devices/virtual/block/dm-0/slaves/mmcblk0p1"
ln -s "$R/sys/devices/platform/14160000.pcie/nvme0n1/nvme0n1p1" "$R/sys/devices/virtual/block/dm-0/slaves/nvme0n1p1"
ln -s "$R/sys/devices/virtual/block/dm-0" "$R/sys/dev/block/252:0"
root_on 252:0
run
if [ "$pre_rc" -ne 0 ] && [ -z "$target" ] && [ -z "$switched" ] &&
  echo "$pre_out" | grep -q "cannot tell which disk"; then
  pass "a device-mapper root over two disks is not attributed to either"
else
  fail "dm root over two disks: target '$target' pre=$pre_rc switched='$switched'"
fi

# Two mountinfo lines for /: an early mount from the SD card, then the rootfs
# from the NVMe mounted over it. The last line is what / is now.
fresh
two_disks
root_on 179:1 259:1
run
if [ "$pre_rc" -eq 0 ] && [ "$target" = "nvme0n1p2" ] && [ "$post_rc" -eq 0 ] && [ -n "$switched" ]; then
  pass "with / mounted twice, the last mount decides the booted disk"
else
  fail "overmounted /: target '$target' pre=$pre_rc post=$post_rc"
fi

echo
if [ "$failures" -eq 0 ]; then
  echo "test-rootfs-ab-target: PASS"
  exit 0
fi
echo "test-rootfs-ab-target: FAIL ($failures)"
exit 1
