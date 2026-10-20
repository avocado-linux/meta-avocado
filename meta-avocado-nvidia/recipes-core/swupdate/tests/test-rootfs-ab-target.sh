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
printf '#!/bin/sh\nexit 1\n' > "$work/bin/findmnt"
chmod +x "$work/bin/"*

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

# / mounted from <maj:min>
root_on() {
  printf '22 1 %s / / ro,relatime shared:1 - squashfs /dev/x ro\n' "$1" > "$R/proc/self/mountinfo"
}

two_disks() {
  disk 3400000.mmc mmcblk0 mmcblk0p1=APP:179:1 mmcblk0p2=APP_b:179:2
  disk 14160000.pcie nvme0n1 nvme0n1p1=APP:259:1 nvme0n1p2=APP_b:259:2
}

# Sets pre_rc, post_rc, target (basename the pre-install chose), switched.
run() {
  : > "$work/nvbootctrl.log"
  local env=(PATH="$work/bin:$PATH" SLOT="${SLOT:-0}" NVBOOTCTRL_LOG="$work/nvbootctrl.log")
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

echo
if [ "$failures" -eq 0 ]; then
  echo "test-rootfs-ab-target: PASS"
  exit 0
fi
echo "test-rootfs-ab-target: FAIL ($failures)"
exit 1
