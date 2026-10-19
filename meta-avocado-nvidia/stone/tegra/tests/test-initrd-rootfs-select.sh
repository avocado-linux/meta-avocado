#!/usr/bin/env bash
#
# avocado-tegra-init must mount the rootfs the command line pins, not whichever
# disk carrying PARTLABEL=APP the kernel enumerated first.
#
# Observed on a Jetson Orin Nano with a provisioned SD card and a provisioned
# NVMe: both carry APP, the SD controller is up ~2s before PCIe, and the initrd
# mounted the SD rootfs under the NVMe kernel with nothing logged.
#
# This runs the real init script with its /proc, /sys and /dev/disk paths
# pointed into a scratch tree and blkid/lsblk/mount/hexdump stubbed, then checks
# which device it mounted on /sysroot.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$SCRIPT_DIR/../../../recipes-core/avocado-tegra-init/files/avocado-tegra-init"
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

echo "test-initrd-rootfs-select: $TARGET"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

PA=49138F00-0C01-4B18-88A8-40E5D8E8DD54
PB=623AFD90-F9EA-4C59-A65E-9AF6306AC837
pa=$(echo "$PA" | tr 'A-F' 'a-f')
pb=$(echo "$PB" | tr 'A-F' 'a-f')

mkdir -p "$work/bin"

# blkid over a table of "<dev> <PARTLABEL> <PARTUUID>" lines, in the order the
# kernel enumerated them.
cat > "$work/bin/blkid" <<'EOF'
#!/bin/sh
[ "${1:-}" = "--probe" ] && exit 0
first=; key=; val=
while [ $# -gt 0 ]; do
  case "$1" in
    -l) first=yes ;;
    -t) key="${2%%=*}"; val="${2#*=}"; shift ;;
  esac
  shift
done
found=1
while read -r dev label uuid; do
  case "$key" in
    PARTLABEL) [ "$label" = "$val" ] || continue ;;
    PARTUUID) [ "$uuid" = "$val" ] || continue ;;
  esac
  echo "$dev: PARTLABEL=\"$label\" PARTUUID=\"$uuid\""
  found=0
  [ -n "$first" ] && break
done < "$BLKID_TABLE"
exit $found
EOF
cat > "$work/bin/lsblk" <<'EOF'
#!/bin/sh
exit 0
EOF
cat > "$work/bin/mount" <<'EOF'
#!/bin/sh
echo "$1 $2" >> "$MOUNT_LOG"
EOF
# Prints the BootChainOsCurrent pair the case set, as hexdump would.
cat > "$work/bin/hexdump" <<'EOF'
#!/bin/sh
[ -n "${BOOTCHAIN:-}" ] || exit 1
echo " $BOOTCHAIN"
EOF
cat > "$work/bin/sleep" <<'EOF'
#!/bin/sh
exit 0
EOF
chmod +x "$work/bin/"*

# Point the script's fixed paths into the scratch tree.
sed -e "s,/proc/cmdline,$work/root/cmdline,g" \
  -e "s,/dev/disk/by-partuuid/,$work/root/by-partuuid/,g" \
  -e "s,/sys/block,$work/root/sys/block,g" \
  "$TARGET" > "$work/init"

# scenario <cmdline> <symlinks: uuid=dev,...> ; table on stdin
# Sets rc, out, rootfs (device mounted on /sysroot, empty if none).
scenario() {
  rm -rf "$work/root"
  mkdir -p "$work/root/by-partuuid" "$work/root/sys/block" "$work/root/dev"
  echo "$1" > "$work/root/cmdline"
  cat > "$work/table"
  while read -r dev _; do : > "$work/root/dev/$dev"; done < "$work/table"
  sed -i "s,^,$work/root/dev/," "$work/table"
  local link
  for link in ${2//,/ }; do
    ln -s "$work/root/dev/${link#*=}" "$work/root/by-partuuid/${link%%=*}"
  done
  : > "$work/mounts"
  out=$(PATH="$work/bin:$PATH" BLKID_TABLE="$work/table" MOUNT_LOG="$work/mounts" \
    BOOTCHAIN="${BOOTCHAIN:-}" sh "$work/init" 2>&1)
  rc=$?
  rootfs=$(awk '$2=="/sysroot"{print $1}' "$work/mounts")
  rootfs=${rootfs##*/}
}

TWO_DISKS="mmcblk0p1 APP $pa-sd
mmcblk0p2 APP_b $pb-sd
nvme0n1p1 APP $pa
nvme0n1p2 APP_b $pb"

CMDLINE="avocado.root_partuuid=$PA avocado.root_partuuid_b=$PB"

scenario "$CMDLINE" "$pa=nvme0n1p1,$pb=nvme0n1p2" <<<"$TWO_DISKS"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "nvme0n1p1" ]; then
  pass "the pinned NVMe wins over an SD card enumerated first with the same label"
else
  fail "expected nvme0n1p1, mounted '${rootfs}' (rc=$rc): $(echo "$out" | tail -3)"
fi

BOOTCHAIN="6 1" scenario "$CMDLINE" "$pa=nvme0n1p1,$pb=nvme0n1p2" <<<"$TWO_DISKS"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "nvme0n1p2" ]; then
  pass "BootChainOsCurrent slot 1 selects the slot-B PARTUUID"
else
  fail "slot B via BootChainOsCurrent: mounted '${rootfs}' (rc=$rc)"
fi

scenario "boot.slot_suffix=_b $CMDLINE" "$pa=nvme0n1p1,$pb=nvme0n1p2" <<<"$TWO_DISKS"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "nvme0n1p2" ]; then
  pass "boot.slot_suffix=_b selects the slot-B PARTUUID"
else
  fail "slot B via boot.slot_suffix: mounted '${rootfs}' (rc=$rc)"
fi

# No by-partuuid symlink yet: blkid must still find it, from the lowercased form.
scenario "$CMDLINE" "" <<<"$TWO_DISKS"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "nvme0n1p1" ]; then
  pass "without the udev symlink, blkid resolves the pinned PARTUUID"
else
  fail "blkid path: mounted '${rootfs}' (rc=$rc)"
fi

# Pinned PARTUUID absent and two disks carry APP: refuse rather than guess.
scenario "$CMDLINE" "" <<<"mmcblk0p1 APP x-sd
nvme0n1p1 APP x-nvme"
if [ "$rc" -ne 0 ] && [ -z "$rootfs" ] && echo "$out" | grep -q "refusing to guess"; then
  pass "an absent pin with two APP disks stops instead of mounting one"
else
  fail "ambiguous fallback: mounted '${rootfs}' (rc=$rc)"
fi

# Pinned PARTUUID absent and exactly one APP: boot it, and say so.
scenario "$CMDLINE" "" <<<"nvme0n1p1 APP x-nvme"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "nvme0n1p1" ] && echo "$out" | grep -q "WARNING: PARTUUID="; then
  pass "an absent pin with one APP disk boots it with a warning"
else
  fail "single-disk fallback: mounted '${rootfs}' (rc=$rc)"
fi

# No pin on the command line (prebuilt boot.img): label discovery as before.
scenario "" "" <<<"$TWO_DISKS"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "mmcblk0p1" ]; then
  pass "without a pin, discovery by label is unchanged"
else
  fail "unpinned: mounted '${rootfs}' (rc=$rc)"
fi

echo
if [ "$failures" -eq 0 ]; then
  echo "test-initrd-rootfs-select: PASS"
  exit 0
fi
echo "test-initrd-rootfs-select: FAIL ($failures)"
exit 1
