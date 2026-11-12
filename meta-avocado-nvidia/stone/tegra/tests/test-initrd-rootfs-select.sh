#!/usr/bin/env bash
#
# avocado-tegra-init must mount the rootfs the command line pins, not whichever
# disk carrying PARTLABEL=APP the kernel enumerated first.
#
# Observed on a Jetson Orin Nano with a provisioned SD card and a provisioned
# NVMe: both carry APP, the SD controller is up ~2s before PCIe, and the initrd
# mounted the SD rootfs under the NVMe kernel with nothing logged.
#
# The pin lives only in the boot.img provisioning repacks, so an OTA that writes
# a build-hook boot.img drops it. Without a pin the init must take the rootfs on
# the disk firmware booted from, which the BootCurrent entry names by its
# controller.
#
# This runs the real init script with its /proc, /sys, efivars and /dev/disk
# paths pointed into a scratch tree and blkid/lsblk/mount stubbed, then checks
# which device it mounted on /sysroot. AVOCADO_TEGRA_INIT runs it against
# another copy of the script; INIT_SH picks the shell (e.g. "busybox sh").

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${AVOCADO_TEGRA_INIT:-$SCRIPT_DIR/../../../recipes-core/avocado-tegra-init/files/avocado-tegra-init}"
INIT_SH="${INIT_SH:-sh}"
REAL_HEXDUMP="$(command -v hexdump)" || {
  echo "hexdump not found" >&2
  exit 1
}
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

# blkid over a table of "<dev> <PARTLABEL> <PARTUUID> [<after>]" lines, in the
# order the kernel enumerated them. A row with <after> stays invisible until
# the init has slept that many times, which is how a disk that enumerates late
# (PCIe after SD) is modelled.
cat >"$work/bin/blkid" <<'EOF'
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
ticks=$(wc -l < "$TICKS")
found=1
while read -r dev label uuid after; do
  [ "${after:-0}" -le "$ticks" ] || continue
  case "$key" in
    "") ;;
    PARTLABEL) [ "$label" = "$val" ] || continue ;;
    PARTUUID) [ "$uuid" = "$val" ] || continue ;;
    *) continue ;;
  esac
  echo "$dev: PARTLABEL=\"$label\" PARTUUID=\"$uuid\""
  found=0
  [ -n "$first" ] && break
done < "$BLKID_TABLE"
exit $found
EOF
cat >"$work/bin/lsblk" <<'EOF'
#!/bin/sh
exit 0
EOF
cat >"$work/bin/mount" <<'EOF'
#!/bin/sh
echo "$1 $2" >> "$MOUNT_LOG"
EOF
# Prints the BootChainOsCurrent pair the case set, as hexdump would; any other
# efivar is a real file in the scratch tree and goes to the real hexdump. Like
# efivarfs, it refuses to seek: hexdump -s there fails with "Illegal seek".
cat >"$work/bin/hexdump" <<'EOF'
#!/bin/sh
echo "$*" >> "$HEXDUMP_LOG"
for a in "$@"; do
  case "$a" in
    -s | -s*)
      echo "hexdump: $(eval echo "\${$#}"): Illegal seek" >&2
      exit 1
      ;;
  esac
done
case "$*" in
  *BootChainOsCurrent*)
    [ -n "${BOOTCHAIN:-}" ] || exit 1
    echo " $BOOTCHAIN"
    ;;
  *) exec "$REAL_HEXDUMP" "$@" ;;
esac
EOF
# Each sleep is one tick of the wait loops; blkid reads the count.
cat >"$work/bin/sleep" <<'EOF'
#!/bin/sh
echo >> "$TICKS"
EOF
chmod +x "$work/bin/"*

# Point the script's fixed paths into the scratch tree.
sed -e "s,/proc/cmdline,$work/root/cmdline,g" \
  -e "s,/dev/disk/by-partuuid/,$work/root/by-partuuid/,g" \
  -e "s,/sys/block,$work/root/sys/block,g" \
  -e "s,/sys/class/block,$work/root/sys/class/block,g" \
  -e "s,/sys/firmware/efi/efivars,$work/root/efivars,g" \
  "$TARGET" >"$work/init"

# Controllers as the platform devices of an Orin: NVMe behind the PCIe
# controller at 0x14160000, the SD card at 0x3400000, USB disks at 0x3610000.
# CTRL_NVME, CTRL_SD and CTRL_USB override them.
controller_of() {
  case "$1" in
    nvme*) echo "${CTRL_NVME:-14160000.pcie}" ;;
    mmcblk*) echo "${CTRL_SD:-3400000.mmc}" ;;
    *) echo "${CTRL_USB:-3610000.usb}" ;;
  esac
}

# <hex> as 8 little-endian bytes, printf-escaped.
le64() {
  local h i out=""
  h=$(printf '%016x' "$((0x$1))")
  for i in 14 12 10 8 6 4 2 0; do out="$out\\x${h:$i:2}"; done
  printf '%s' "$out"
}

# efivars BootCurrent=<BOOT_NUM> and Boot<BOOT_NUM>, a disk entry shaped like
# the Jetson's: VenHw(...)/MemoryMapped(11,<base>,<base>+0x1ffff)/End.
# BOOT_KIND picks a malformed or signal-less variant:
#   mm       the disk entry above (default)
#   nomm     VenHw/FvFile/End, as an FV boot has: no MemoryMapped node
#   optdata  VenHw/End, then OptionalData that happens to hold a MemoryMapped
#            node naming <base>; nothing past End is a device path
#   truncmm  VenHw, then a MemoryMapped node cut off after its start address
#   short    an entry shorter than the EFI_LOAD_OPTION header
write_boot_entry() {
  local g=8be4df61-93ca-11d2-aa0d-00e098032b8c num="${BOOT_NUM:-0001}"
  local head venhw mm end
  mkdir -p "$work/root/efivars"
  printf '%b' "\\x07\\x00\\x00\\x00\\x${num:2:2}\\x${num:0:2}" >"$work/root/efivars/BootCurrent-$g"
  head="\\x07\\x00\\x00\\x00\\x01\\x00\\x00\\x00\\x30\\x00N\\x00V\\x00\\x00\\x00"
  venhw="\\x01\\x04\\x14\\x00\\x2c\\x43\\x5a\\x1e\\x66\\x04\\x31\\x4d\\xb0\\x09\\xd4\\xd9\\x23\\x92\\x71\\xd3"
  mm="\\x01\\x03\\x18\\x00\\x0b\\x00\\x00\\x00$(le64 "$1")$(le64 "$(printf '%x' $((0x$1 + 0x1ffff)))")"
  end="\\x7f\\xff\\x04\\x00"
  local body
  case "${BOOT_KIND:-mm}" in
    mm) body="$head$venhw$mm$end" ;;
    nomm) body="$head$venhw\\x04\\x06\\x14\\x00\\x2c\\x43\\x5a\\x1e\\x66\\x04\\x31\\x4d\\xb0\\x09\\xd4\\xd9\\x23\\x92\\x71\\xd3$end" ;;
    optdata) body="$head$venhw$end$mm$end" ;;
    truncmm) body="$head$venhw\\x01\\x03\\x18\\x00\\x0b\\x00\\x00\\x00$(le64 "$1")" ;;
    short) body="\\x07\\x00\\x00\\x00\\x01\\x00\\x00\\x00" ;;
  esac
  printf '%b' "$body" >"$work/root/efivars/Boot$num-$g"
}

# scenario <cmdline> <symlinks: uuid=dev,...> ; table on stdin
# BOOT_CTRL=<hex base> adds a BootCurrent entry naming that controller.
# Sets rc, out, rootfs (device mounted on /sysroot, empty if none), and
# leaves every hexdump call in $work/hexdump.log.
scenario() {
  rm -rf "$work/root"
  mkdir -p "$work/root/by-partuuid" "$work/root/sys/block" "$work/root/sys/class/block" "$work/root/dev"
  echo "$1" >"$work/root/cmdline"
  cat >"$work/table"
  local dev disk part
  while read -r dev _; do
    : >"$work/root/dev/$dev"
    case "$dev" in
      nvme* | mmcblk*) disk=${dev%p[0-9]*} ;;
      *) disk=${dev%%[0-9]*} ;;
    esac
    part="$work/root/devices/platform/bus@0/$(controller_of "$dev")/x/$disk/$dev"
    mkdir -p "$part"
    ln -s "$part" "$work/root/sys/class/block/$dev"
  done <"$work/table"
  sed -i "s,^,$work/root/dev/," "$work/table"
  [ -z "${BOOT_CTRL:-}" ] || write_boot_entry "$BOOT_CTRL"
  local link
  for link in ${2//,/ }; do
    ln -s "$work/root/dev/${link#*=}" "$work/root/by-partuuid/${link%%=*}"
  done
  : >"$work/mounts"
  : >"$work/ticks"
  : >"$work/hexdump.log"
  out=$(PATH="$work/bin:$PATH" BLKID_TABLE="$work/table" MOUNT_LOG="$work/mounts" \
    TICKS="$work/ticks" HEXDUMP_LOG="$work/hexdump.log" \
    BOOTCHAIN="${BOOTCHAIN:-}" REAL_HEXDUMP="$REAL_HEXDUMP" $INIT_SH "$work/init" 2>&1)
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

# A pin still wins over the boot entry when both are present.
BOOT_CTRL=3400000 scenario "$CMDLINE" "$pa=nvme0n1p1,$pb=nvme0n1p2" <<<"$TWO_DISKS"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "nvme0n1p1" ]; then
  pass "the pin wins over a boot entry naming another disk"
else
  fail "pin vs boot entry: mounted '${rootfs}' (rc=$rc)"
fi

# No pin (an OTA wrote a build-hook boot.img): the disk firmware booted wins
# over the SD card enumerated first.
BOOT_CTRL=14160000 scenario "" "" <<<"$TWO_DISKS"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "nvme0n1p1" ]; then
  pass "without a pin, the booted NVMe wins over the SD card"
else
  fail "unpinned, booted NVMe: mounted '${rootfs}' (rc=$rc): $(echo "$out" | tail -3)"
fi

BOOT_CTRL=14160000 BOOTCHAIN="6 1" scenario "" "" <<<"$TWO_DISKS"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "nvme0n1p2" ]; then
  pass "without a pin, slot B comes from the booted NVMe"
else
  fail "unpinned, booted NVMe, slot B: mounted '${rootfs}' (rc=$rc)"
fi

BOOT_CTRL=3400000 scenario "" "" <<<"nvme0n1p1 APP $pa
mmcblk0p1 APP $pa-sd"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "mmcblk0p1" ]; then
  pass "without a pin, a booted SD card wins even when the NVMe is listed first"
else
  fail "unpinned, booted SD: mounted '${rootfs}' (rc=$rc)"
fi

# The pin is on the command line but its partition is gone, and two disks
# carry APP: the booted disk settles it instead of refusing.
BOOT_CTRL=14160000 scenario "$CMDLINE" "" <<<"mmcblk0p1 APP x-sd
nvme0n1p1 APP x-nvme"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "nvme0n1p1" ] && echo "$out" | grep -q "disk firmware booted from"; then
  pass "an absent pin with two APP disks boots the booted one, with a warning"
else
  fail "absent pin, booted NVMe: mounted '${rootfs}' (rc=$rc)"
fi

# The boot entry names a controller with no APP behind it: still ambiguous.
BOOT_CTRL=3610000 scenario "" "" <<<"$TWO_DISKS"
if [ "$rc" -ne 0 ] && [ -z "$rootfs" ] && echo "$out" | grep -q "refusing to guess"; then
  pass "a boot entry naming neither APP disk stops"
else
  fail "boot entry on another controller: mounted '${rootfs}' (rc=$rc)"
fi

# Two APP disks behind the booted controller: the signal does not decide.
BOOT_CTRL=3610000 scenario "" "" <<<"sda1 APP u1
sdb1 APP u2"
if [ "$rc" -ne 0 ] && [ -z "$rootfs" ] && echo "$out" | grep -q "refusing to guess"; then
  pass "two APP disks behind the booted controller stop"
else
  fail "two disks on the booted controller: mounted '${rootfs}' (rc=$rc)"
fi

# No pin and no boot entry: two APP disks stop instead of taking the first.
scenario "" "" <<<"$TWO_DISKS"
if [ "$rc" -ne 0 ] && [ -z "$rootfs" ] && echo "$out" | grep -q "refusing to guess"; then
  pass "without a pin or a boot entry, two APP disks stop"
else
  fail "unpinned, no boot entry: mounted '${rootfs}' (rc=$rc)"
fi

# No pin and no boot entry, one APP disk: it boots.
scenario "" "" <<<"nvme0n1p1 APP $pa"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "nvme0n1p1" ]; then
  pass "without a pin or a boot entry, a single APP disk boots"
else
  fail "unpinned, single disk: mounted '${rootfs}' (rc=$rc)"
fi

# A pin that resolves never reads the boot entry.
BOOT_CTRL=3400000 scenario "$CMDLINE" "$pa=nvme0n1p1,$pb=nvme0n1p2" <<<"$TWO_DISKS"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "nvme0n1p1" ] && ! grep -q -E 'BootCurrent-|Boot[0-9A-F]{4}-' "$work/hexdump.log"; then
  pass "a resolved pin reads no BootCurrent or Boot#### variable"
else
  fail "pinned success read the boot entry: $(grep -E 'BootCurrent-|Boot[0-9A-F]{4}-' "$work/hexdump.log" | head -2)"
fi

# BootCurrent 0x000A names Boot000A: efivarfs names are upper-case hex.
BOOT_NUM=000A BOOT_CTRL=14160000 scenario "" "" <<<"$TWO_DISKS"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "nvme0n1p1" ]; then
  pass "a BootCurrent with a hex letter finds its upper-case Boot#### entry"
else
  fail "BootCurrent 0x000A: mounted '${rootfs}' (rc=$rc)"
fi

# Unpinned: the booted NVMe enumerates three ticks after the SD card. The init
# must wait for it rather than settle on the SD card it sees first.
BOOT_CTRL=14160000 scenario "" "" <<<"mmcblk0p1 APP $pa-sd
nvme0n1p1 APP $pa 3"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "nvme0n1p1" ] && ! echo "$out" | grep -q -e "is absent" -e "not behind"; then
  pass "without a pin, the init waits for a booted NVMe that enumerates late"
else
  fail "unpinned late NVMe: mounted '${rootfs}' (rc=$rc): $(echo "$out" | tail -2)"
fi

# Pinned: the pinned partition enumerates three ticks after an SD card APP.
scenario "$CMDLINE" "" <<<"mmcblk0p1 APP x-sd
nvme0n1p1 APP $pa 3"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "nvme0n1p1" ] && ! echo "$out" | grep -q -e "is absent" -e "not behind"; then
  pass "the init waits for a pinned partition that enumerates late"
else
  fail "pinned late NVMe: mounted '${rootfs}' (rc=$rc): $(echo "$out" | tail -2)"
fi

# The only APP is on a disk the boot entry does not name: boot it, but say so.
BOOT_CTRL=14160000 scenario "" "" <<<"mmcblk0p1 APP $pa-sd"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "mmcblk0p1" ] \
  && echo "$out" | grep -q "not behind the booted controller 14160000"; then
  pass "a single APP off the booted controller boots with a warning"
else
  fail "single APP off controller: mounted '${rootfs}' (rc=$rc): $(echo "$out" | tail -2)"
fi

# The controller match is anchored: 14160000 must not match 114160000.mmc.
CTRL_SD=114160000.mmc BOOT_CTRL=14160000 scenario "" "" <<<"$TWO_DISKS"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "nvme0n1p1" ]; then
  pass "the booted controller matches a whole platform device name only"
else
  fail "anchoring: mounted '${rootfs}' (rc=$rc): $(echo "$out" | tail -2)"
fi

# An FV boot entry has no MemoryMapped node: no signal, so two APPs stop.
BOOT_KIND=nomm BOOT_CTRL=14160000 scenario "" "" <<<"$TWO_DISKS"
if [ "$rc" -ne 0 ] && [ -z "$rootfs" ] && echo "$out" | grep -q "controller 'none'"; then
  pass "a boot entry with no MemoryMapped node gives no signal"
else
  fail "no MemoryMapped node: mounted '${rootfs}' (rc=$rc)"
fi

# A MemoryMapped pattern after the End node is OptionalData, not a device path.
BOOT_KIND=optdata BOOT_CTRL=14160000 scenario "" "" <<<"$TWO_DISKS"
if [ "$rc" -ne 0 ] && [ -z "$rootfs" ] && echo "$out" | grep -q "controller 'none'"; then
  pass "bytes past the device path End node are not read as a node"
else
  fail "OptionalData read as a node: mounted '${rootfs}' (rc=$rc)"
fi

# A MemoryMapped node cut short by the end of the variable is not trusted.
BOOT_KIND=truncmm BOOT_CTRL=14160000 scenario "" "" <<<"$TWO_DISKS"
if [ "$rc" -ne 0 ] && [ -z "$rootfs" ] && echo "$out" | grep -q "controller 'none'"; then
  pass "a truncated MemoryMapped node gives no signal"
else
  fail "truncated MemoryMapped node: mounted '${rootfs}' (rc=$rc)"
fi

# A Boot#### shorter than its own header must not take the init down.
BOOT_KIND=short BOOT_CTRL=14160000 scenario "" "" <<<"nvme0n1p1 APP $pa"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "nvme0n1p1" ]; then
  pass "a truncated boot entry falls back to the label rule"
else
  fail "short boot entry: mounted '${rootfs}' (rc=$rc): $(echo "$out" | tail -2)"
fi

# No boot signal, two APP disks, and root= names one of them: take it.
scenario "root=PARTUUID=$pa" "" <<<"$TWO_DISKS"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "nvme0n1p1" ] && echo "$out" | grep -q "the one root=PARTUUID=$pa names"; then
  pass "without a pin or a boot entry, root= naming one APP disk settles it"
else
  fail "root= names one: mounted '${rootfs}' (rc=$rc): $(echo "$out" | tail -2)"
fi

# The same, typed in the layout XML's upper case: blkid and udev hold the
# PARTUUID lower-cased, so the value has to be lowered before matching.
scenario "root=PARTUUID=$PA" "" <<<"$TWO_DISKS"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "nvme0n1p1" ]; then
  pass "an upper-case root=PARTUUID= naming one APP disk settles it"
else
  fail "upper-case root= names one: mounted '${rootfs}' (rc=$rc): $(echo "$out" | tail -2)"
fi

# No APP label anywhere: Path 3 takes root=PARTUUID=, in upper case too.
scenario "root=PARTUUID=$PA" "" <<<"nvme0n1p1 ROOTFS $pa"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "nvme0n1p1" ]; then
  pass "with no APP label, an upper-case root=PARTUUID= is resolved"
else
  fail "Path 3 upper-case root=: mounted '${rootfs}' (rc=$rc): $(echo "$out" | tail -2)"
fi

# root= that names neither APP disk, or both, still stops.
scenario "root=PARTUUID=nowhere" "" <<<"$TWO_DISKS"
if [ "$rc" -ne 0 ] && [ -z "$rootfs" ] && echo "$out" | grep -q "refusing to guess"; then
  pass "root= naming neither APP disk stops"
else
  fail "root= names neither: mounted '${rootfs}' (rc=$rc)"
fi

scenario "root=PARTLABEL=APP" "" <<<"$TWO_DISKS"
if [ "$rc" -ne 0 ] && [ -z "$rootfs" ] && echo "$out" | grep -q "refusing to guess"; then
  pass "root= naming both APP disks stops"
else
  fail "root= names both: mounted '${rootfs}' (rc=$rc)"
fi

# The pin is absent, two disks carry APP, and root= names one of them.
scenario "$CMDLINE root=PARTUUID=x-nvme" "" <<<"mmcblk0p1 APP x-sd
nvme0n1p1 APP x-nvme"
if [ "$rc" -eq 0 ] && [ "$rootfs" = "nvme0n1p1" ] && echo "$out" | grep -q "WARNING: PARTUUID=$PA is absent and 2"; then
  pass "an absent pin with two APP disks boots the one root= names, with a warning"
else
  fail "absent pin, root= names one: mounted '${rootfs}' (rc=$rc): $(echo "$out" | tail -2)"
fi

echo
if [ "$failures" -eq 0 ]; then
  echo "test-initrd-rootfs-select: PASS"
  exit 0
fi
echo "test-initrd-rootfs-select: FAIL ($failures)"
exit 1
