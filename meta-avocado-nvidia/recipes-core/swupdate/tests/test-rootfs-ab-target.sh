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
# This runs the real rootfs-pre.sh and rootfs-post.sh with /sys, /proc/mounts
# and /tmp pointed into a scratch tree and nvbootctrl, udevadm, blkid and
# findmnt stubbed, then checks which device the pre-install chose and whether
# the post-install switched the slot. Device names stay /dev/..., since the
# scripts derive the disk from them; only the block-device tests are pointed at
# regular files under the scratch tree.

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
cat >"$work/bin/nvbootctrl" <<'EOF'
#!/bin/sh
case "$*" in
  *get-current-slot*) echo "$SLOT" ;;
  *set-active-boot-slot*) echo "$*" >>"$NVBOOTCTRL_LOG" ;;
esac
EOF
printf '#!/bin/sh\nexit 0\n' >"$work/bin/udevadm"
printf '#!/bin/sh\nexit 0\n' >"$work/bin/blkid"
# findmnt: "-n -o SOURCE /" prints $ROOTSRC (nothing when unset, which sends
# the scripts to /proc/mounts); "-n -S <dev>" succeeds only for the device
# whose basename is $MOUNTED; anything else reports nothing mounted.
cat >"$work/bin/findmnt" <<'EOF'
#!/bin/sh
case "$*" in
  "-n -o SOURCE /") [ -n "${ROOTSRC:-}" ] && echo "$ROOTSRC"; exit 0 ;;
  "-n -S "*) [ -n "${MOUNTED:-}" ] && [ "${3##*/}" = "$MOUNTED" ] && exit 0 ;;
esac
exit 1
EOF
chmod +x "$work/bin/"*

# SWUpdate runs each script on its own, so the helpers are carried in both.
# A fix applied to one copy only must fail here.
for fn in log active_rootfs_dev disk_of partname_of resolve_partlabel_on_disk; do
  a=$(sed -n "/^$fn() {/,/^}/p" "$SRC/rootfs-pre.sh")
  b=$(sed -n "/^$fn() {/,/^}/p" "$SRC/rootfs-post.sh")
  if [ -n "$a" ] && [ "$a" = "$b" ]; then
    pass "$fn is the same in rootfs-pre.sh and rootfs-post.sh"
  else
    fail "$fn differs between rootfs-pre.sh and rootfs-post.sh (or is missing)"
  fi
done

# /tmp/ goes first: $R lives under /tmp, and sed applies each expression to
# the output of the one before. A block-device test on "<path>" becomes an
# existence test on "$R<path>".
for s in rootfs-pre.sh rootfs-post.sh; do
  sed -e "s,/tmp/,$R/tmp/,g" \
    -e "s,/sys/,$R/sys/,g" \
    -e "s,/proc/mounts,$R/proc/mounts,g" \
    -e "s|\[ \(! \)\{0,1\}-b \"\([^\"]*\)\" \]|[ \1-e \"$R\2\" ]|g" \
    "$SRC/$s" >"$work/$s"
done
for want in "$R/sys/block" "$R/proc/mounts" "-e \"$R\$cand\""; do
  grep -qF -- "$want" "$work/rootfs-pre.sh" || {
    fail "rewrite did not land in rootfs-pre.sh: $want"
    exit 1
  }
done
grep -qF -- "-e \"$R\$TEGRA_TARGET_DEV\"" "$work/rootfs-post.sh" || {
  fail "rewrite did not land in rootfs-post.sh"
  exit 1
}

# disk <disk> <part>=<label> ...
disk() {
  local d=$1 p name
  shift
  mkdir -p "$R/sys/block/$d"
  for p in "$@"; do
    name=${p%%=*}
    mkdir -p "$R/sys/block/$d/$name"
    printf 'MAJOR=259\nDEVNAME=%s\nDEVTYPE=partition\nPARTNAME=%s\n' \
      "$name" "${p#*=}" >"$R/sys/block/$d/$name/uevent"
    : >"$R/dev/$name"
  done
}

fresh() {
  rm -rf "$R"
  mkdir -p "$R/proc" "$R/sys/block" "$R/dev" "$R/tmp"
  : >"$R/proc/mounts"
}

two_disks() {
  disk mmcblk0 mmcblk0p1=APP mmcblk0p2=APP_b
  disk nvme0n1 nvme0n1p1=APP nvme0n1p2=APP_b
}

# Sets pre_rc, post_rc, target (basename the pre-install chose), switched.
run() {
  : >"$work/nvbootctrl.log"
  local env=(PATH="$work/bin:$PATH" SLOT="${SLOT:-0}" NVBOOTCTRL_LOG="$work/nvbootctrl.log"
    ROOTSRC="${ROOTSRC:-}" MOUNTED="${MOUNTED:-}")
  pre_out=$(env "${env[@]}" sh "$work/rootfs-pre.sh" 2>&1)
  pre_rc=$?
  target=$(sed -n 's/^TEGRA_TARGET_DEV=//p' "$R/tmp/tegra-ab-vars" 2>/dev/null)
  target=${target##*/}
  if [ -n "${FORGE_TARGET:-}" ] && [ -f "$R/tmp/tegra-ab-vars" ]; then
    sed -i "s,^TEGRA_TARGET_DEV=.*,TEGRA_TARGET_DEV=/dev/$FORGE_TARGET," "$R/tmp/tegra-ab-vars"
  fi
  post_out=$(env "${env[@]}" sh "$work/rootfs-post.sh" 2>&1)
  post_rc=$?
  switched=$(cat "$work/nvbootctrl.log")
}

fresh
two_disks
ROOTSRC=/dev/nvme0n1p1 run
if [ "$pre_rc" -eq 0 ] && [ "$target" = "nvme0n1p2" ] && [ "$post_rc" -eq 0 ] && [ -n "$switched" ]; then
  pass "booted from NVMe with both disks labelled, APP_b on the NVMe is written"
else
  fail "booted NVMe: target '$target' pre=$pre_rc post=$post_rc: $(echo "$pre_out$post_out" | grep ERROR | head -2)"
fi

fresh
two_disks
ROOTSRC=/dev/mmcblk0p1 run
if [ "$pre_rc" -eq 0 ] && [ "$target" = "mmcblk0p2" ] && [ "$post_rc" -eq 0 ] && [ -n "$switched" ]; then
  pass "booted from SD with both disks labelled, APP_b on the SD card is written"
else
  fail "booted SD: target '$target' pre=$pre_rc post=$post_rc"
fi

fresh
two_disks
SLOT=1 ROOTSRC=/dev/nvme0n1p2 run
if [ "$pre_rc" -eq 0 ] && [ "$target" = "nvme0n1p1" ] && [ "$post_rc" -eq 0 ]; then
  pass "slot B running from NVMe writes APP on the NVMe"
else
  fail "slot B on NVMe: target '$target' pre=$pre_rc post=$post_rc"
fi

# findmnt prints nothing: the root device comes from /proc/mounts instead.
fresh
two_disks
printf '/dev/mmcblk0p1 / erofs ro,relatime 0 0\n' >"$R/proc/mounts"
run
if [ "$pre_rc" -eq 0 ] && [ "$target" = "mmcblk0p2" ] && [ "$post_rc" -eq 0 ]; then
  pass "without findmnt's answer, /proc/mounts names the booted disk"
else
  fail "/proc/mounts fallback: target '$target' pre=$pre_rc post=$post_rc"
fi

# Two partitions on the booted disk carry the target label: refuse, not choose.
fresh
two_disks
disk nvme0n1 nvme0n1p3=APP_b
ROOTSRC=/dev/nvme0n1p1 run
if [ "$pre_rc" -ne 0 ] && [ -z "$target" ] && [ ! -e "$R/tmp/target_rootfs" ] && [ -z "$switched" ] \
  && echo "$pre_out" | grep -q "2 partitions on /dev/nvme0n1 carry PARTLABEL='APP_b'"; then
  pass "two target partitions on the booted disk refuse"
else
  fail "duplicate target label on booted disk: target '$target' pre=$pre_rc switched='$switched'"
fi

# The booted disk has no APP_b: never fall over to the other disk's.
fresh
disk mmcblk0 mmcblk0p1=APP mmcblk0p2=APP_b
disk nvme0n1 nvme0n1p1=APP
ROOTSRC=/dev/nvme0n1p1 run
if [ "$pre_rc" -ne 0 ] && [ -z "$target" ] && [ -z "$switched" ]; then
  pass "a booted disk with no target slot refuses instead of using another disk's"
else
  fail "booted disk lacks APP_b: target '$target' pre=$pre_rc switched='$switched'"
fi

# nvme0n11 shares nvme0n1's name as a prefix. Its APP_b is not on the booted
# disk and must not make the booted disk's APP_b look ambiguous.
fresh
two_disks
disk nvme0n11 nvme0n11p1=APP nvme0n11p2=APP_b
ROOTSRC=/dev/nvme0n1p1 run
if [ "$pre_rc" -eq 0 ] && [ "$target" = "nvme0n1p2" ] && [ "$post_rc" -eq 0 ]; then
  pass "nvme0n11p2 is not counted as a partition of nvme0n1"
else
  fail "nvme0n11 prefix: target '$target' pre=$pre_rc post=$post_rc"
fi

# nvbootctrl says slot 0 (APP running), but / is APP_b. The nvbootctrl
# cross-check catches it before anything is resolved.
fresh
two_disks
ROOTSRC=/dev/nvme0n1p2 run
if [ "$pre_rc" -ne 0 ] && [ -z "$target" ] && [ -z "$switched" ] \
  && echo "$pre_out" | grep -q "nvbootctrl reports slot 0"; then
  pass "an nvbootctrl slot that disagrees with the mounted root's label refuses"
else
  fail "slot vs mounted label: target '$target' pre=$pre_rc switched='$switched'"
fi

# The same layout makes the target the running rootfs. Whichever guard fires,
# nothing may be written: no symlink, no vars file, no slot switch.
if [ "$pre_rc" -ne 0 ] && [ ! -e "$R/tmp/target_rootfs" ] && [ ! -e "$R/tmp/tegra-ab-vars" ] && [ -z "$switched" ]; then
  pass "a target that is the running rootfs is never written"
else
  fail "target == active: pre=$pre_rc switched='$switched'"
fi

# The target partition is mounted somewhere: refuse rather than write under it.
fresh
two_disks
ROOTSRC=/dev/nvme0n1p1 MOUNTED=nvme0n1p2 run
if [ "$pre_rc" -ne 0 ] && [ -z "$target" ] && [ -z "$switched" ] \
  && echo "$pre_out" | grep -q "appears to be mounted"; then
  pass "a mounted target refuses"
else
  fail "mounted target: target '$target' pre=$pre_rc switched='$switched'"
fi

# / is not a partition. An overlay (or tmpfs) root has no block device, and a
# device-mapper root has no disk disk_of() can name; both refuse rather than
# fall back to the labels, which on a two-disk board would be a guess.
for src in overlay /dev/dm-0 /dev/mapper/root; do
  fresh
  two_disks
  mkdir -p "$R/dev/mapper"
  : >"$R/dev/dm-0"
  : >"$R/dev/mapper/root"
  ROOTSRC=$src run
  if [ "$pre_rc" -ne 0 ] && [ -z "$target" ] && [ ! -e "$R/tmp/target_rootfs" ] && [ -z "$switched" ]; then
    pass "a root on '$src' refuses instead of guessing a disk"
  else
    fail "root on '$src': target '$target' pre=$pre_rc switched='$switched'"
  fi
done

# The post-install is handed a target on the other disk: it must not switch.
fresh
two_disks
ROOTSRC=/dev/nvme0n1p1 FORGE_TARGET=mmcblk0p2 run
if [ "$pre_rc" -eq 0 ] && [ "$post_rc" -ne 0 ] && [ -z "$switched" ] \
  && echo "$post_out" | grep -q "Not switching the boot slot"; then
  pass "the post-install refuses to switch the slot for a target on another disk"
else
  fail "post cross-disk: post=$post_rc switched='$switched'"
fi

# The post-install cannot tell which disk booted: it must not switch either.
fresh
two_disks
printf 'TEGRA_INACTIVE_SLOT=1\nTEGRA_TARGET_DEV=/dev/nvme0n1p2\nTEGRA_TARGET_PARTLABEL=APP_b\nTEGRA_ACTIVE_PARTLABEL=APP\n' \
  >"$R/tmp/tegra-ab-vars"
: >"$work/nvbootctrl.log"
post_out=$(env PATH="$work/bin:$PATH" SLOT=0 NVBOOTCTRL_LOG="$work/nvbootctrl.log" ROOTSRC=overlay \
  sh "$work/rootfs-post.sh" 2>&1)
post_rc=$?
switched=$(cat "$work/nvbootctrl.log")
# It must also say why, rather than report a mismatch against an empty disk.
if [ "$post_rc" -ne 0 ] && [ -z "$switched" ] \
  && echo "$post_out" | grep -q "Could not derive the booted disk from 'overlay'"; then
  pass "the post-install refuses to switch when / is not on a partition"
else
  fail "post, unknown booted disk: post=$post_rc switched='$switched'"
fi

echo
if [ "$failures" -eq 0 ]; then
  echo "test-rootfs-ab-target: PASS"
  exit 0
fi
echo "test-rootfs-ab-target: FAIL ($failures)"
exit 1
