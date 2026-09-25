#!/usr/bin/env bash
# Host test for stone-provision-usb.sh: the target checks that stand between a
# typed device path and a raw dd. Everything that touches a disk is a stub
# (lsblk, findmnt, blockdev, umount, dd), sysfs is a fake tree, and the "disks"
# are regular files under a temp dir, so a stub that fails to intercept writes
# into that dir and nowhere else. Pass another copy of the script (the Intel
# x86-64 siblings share it) as $1 to run the same cases against it.
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts, so bad runs only when the check failed
set -u
here=$(cd "$(dirname "$0")" && pwd); script=${1:-$here/../stone-provision-usb.sh}
w=$(mktemp -d); trap 'rm -rf "$w"' EXIT
pass=0; fail=0; ok(){ echo "  ok   - $1"; pass=$((pass+1)); }; bad(){ echo "  FAIL - $1"; fail=$((fail+1)); }

IMG_BYTES=$((64 * 1048576))

setup() {
  rm -rf "${w:?}/dev" "${w:?}/sys" "${w:?}/build" "${w:?}/st"; mkdir -p "$w/dev/disk/by-id" "$w/dev/mapper" "$w/sys" "$w/build" "$w/st"
  printf '{"runtime":{"platform":"avocado-amd-x86-64-v4"}}' > "$w/manifest.json"
  truncate -s "$IMG_BYTES" "$w/build/avocado-os-avocado-amd-x86-64-v4.img"
  # sda: the host's own disk (root on sda2). sdb: a USB stick. nvme0n1: a
  # second internal disk.
  for d in sda sdb nvme0n1; do mkdir -p "$w/sys/$d"; : > "$w/dev/$d"; echo 1000000 > "$w/sys/$d/size"; echo 0 > "$w/sys/$d/removable"; done
  echo 1 > "$w/sys/sdb/removable"
  for p in sda1 sda2 sdb1 nvme0n1p1; do mkdir -p "$w/sys/$p"; echo 1 > "$w/sys/$p/partition"; : > "$w/dev/$p"; done
  ln -s ../../sda "$w/dev/disk/by-id/ata-HOST-DISK"
  echo "$w/dev/sda2" > "$w/st/rootsrc"
  printf 'sda2 part\nsda disk\n' > "$w/st/lsblk-root"
  echo $((256 * 1048576)) > "$w/st/size"
  : > "$w/st/mounts"; : > "$w/st/umount-fail"
}

mkdir -p "$w/bin"
cat > "$w/bin/findmnt" <<S
#!/bin/bash
echo "findmnt \$*" >> "$w/log"
case " \$* " in
  *" MAJ:MIN "*) cat "$w/st/majmin" 2>/dev/null ;;
  *" -v "*|*" --nofsroot "*) cat "$w/st/rootsrc" ;;
  *) echo "\$(cat "$w/st/rootsrc")[/@]" ;;
esac
S
cat > "$w/bin/lsblk" <<S
#!/bin/bash
echo "lsblk \$*" >> "$w/log"
case " \$* " in
  *" -nslo NAME,TYPE "*) cat "$w/st/lsblk-root" ;;
  # Device type of one device: st/type-<name> when present, else "disk".
  *" -dno TYPE "*) n=\$(basename "\${@: -1}"); cat "$w/st/type-\$n" 2>/dev/null || echo disk ;;
  # Like the real tool: the device itself, then only its own partitions.
  *" -nlo PATH,MOUNTPOINT "*) dev=\${@: -1}; echo "\$dev"; grep -E "^\${dev}p?[0-9]+ " "$w/st/mounts" || true ;;
esac
S
cat > "$w/bin/blockdev" <<S
#!/bin/bash
echo "blockdev \$*" >> "$w/log"
if [ "\$1" = --rereadpt ]; then [ -e "$w/st/busy" ] && { echo "blockdev: ioctl error on BLKRRPART: Device or resource busy" >&2; exit 1; }; exit 0; fi
[ -s "$w/st/size" ] && cat "$w/st/size"
S
cat > "$w/bin/umount" <<S
#!/bin/bash
echo "umount \$*" >> "$w/log"
dev=\${@: -1}
grep -qx "\$dev" "$w/st/umount-fail" && exit 32
grep -v "^\$dev " "$w/st/mounts" > "$w/st/m.tmp"; mv "$w/st/m.tmp" "$w/st/mounts"
S
cat > "$w/bin/swapoff" <<S
#!/bin/bash
echo "swapoff \$*" >> "$w/log"
grep -v "^\$1 " "$w/st/mounts" > "$w/st/m.tmp"; mv "$w/st/m.tmp" "$w/st/mounts"
S
cat > "$w/bin/dd" <<S
#!/bin/bash
echo "dd \$*" >> "$w/log"
S
cat > "$w/bin/sync" <<S
#!/bin/bash
:
S
chmod +x "$w/bin/"*

# $1 = what the operator types as the target. Confirmation is always "yes".
run(){ : > "$w/log"; printf '%s\nyes\n' "$1" | PATH="$w/bin:$PATH" AVOCADO_PROVISION_SYSBLOCK="$w/sys" \
  AVOCADO_STONE_MANIFEST="$w/manifest.json" AVOCADO_STONE_DATA_DIR="$w" AVOCADO_STONE_BUILD_DIR="$w/build" \
  bash "$script" 2>&1; }
wrote(){ grep -q "^dd if=$w/build/" "$w/log"; }

# 1. The happy path: a whole, unmounted, large-enough USB disk gets the image.
setup; out=$(run "$w/dev/sdb"); rc=$?
{ [ $rc -eq 0 ] && grep -q "^dd if=$w/build/avocado-os-avocado-amd-x86-64-v4.img of=$w/dev/sdb " "$w/log"; } \
  && ok "a whole USB disk that fits is written" || bad "happy path: rc=$rc out=[$out] log=$(cat "$w/log")"

# 2. A partition is refused: the image is a whole-disk GPT layout.
setup; out=$(run "$w/dev/sdb1"); rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -qi "partition"; } \
  && ok "a partition target is refused before any write" || bad "partition: rc=$rc out=[$out]"

# 3. The host's own disk reached through a by-id alias is refused.
setup; out=$(run "$w/dev/disk/by-id/ata-HOST-DISK"); rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -qi "root"; } \
  && ok "the root disk is refused through a by-id alias" || bad "alias: rc=$rc out=[$out]"

# 4. Root on dm-crypt over nvme0n1: the physical disk under / is refused.
setup; echo "$w/dev/mapper/root" > "$w/st/rootsrc"; : > "$w/dev/mapper/root"
printf 'root crypt\nnvme0n1p1 part\nnvme0n1 disk\n' > "$w/st/lsblk-root"
out=$(run "$w/dev/nvme0n1"); rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -qi "root"; } \
  && ok "the disk backing a dm-crypt root is refused" || bad "dm-crypt: rc=$rc out=[$out]"

# 5. A target smaller than the image is refused before anything is unmounted.
setup; echo $((32 * 1048576)) > "$w/st/size"; echo "$w/dev/sdb1 /media/stick" > "$w/st/mounts"
out=$(run "$w/dev/sdb"); rc=$?
{ [ $rc -ne 0 ] && ! wrote && ! grep -q '^umount' "$w/log" && echo "$out" | grep -qi "smaller"; } \
  && ok "an undersized target is refused before unmounting or writing" || bad "undersized: rc=$rc out=[$out] log=$(cat "$w/log")"

# 6. An unreadable target size is refused, not treated as "big enough".
setup; : > "$w/st/size"; out=$(run "$w/dev/sdb"); rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -qi "size"; } \
  && ok "an unreadable target size is refused" || bad "no size: rc=$rc out=[$out]"

# 7. A partition that will not unmount stops the run before dd.
setup; echo "$w/dev/sdb1 /media/stick" > "$w/st/mounts"; echo "$w/dev/sdb1" > "$w/st/umount-fail"
out=$(run "$w/dev/sdb"); rc=$?
{ [ $rc -ne 0 ] && ! wrote && grep -q "^umount -A $w/dev/sdb1" "$w/log"; } \
  && ok "a busy partition aborts the run before any write" || bad "busy: rc=$rc out=[$out] log=$(cat "$w/log")"

# 8. Only the target's own partitions are unmounted - never another disk whose
#    name shares the prefix (sdb vs sdbb).
setup; mkdir -p "$w/sys/sdbb1"; echo 1 > "$w/sys/sdbb1/partition"; : > "$w/dev/sdbb1"
printf '%s\n%s\n' "$w/dev/sdb1 /media/stick" "$w/dev/sdbb1 /media/other" > "$w/st/mounts"
out=$(run "$w/dev/sdb"); rc=$?
{ [ $rc -eq 0 ] && grep -q "^umount -A $w/dev/sdb1" "$w/log" && ! grep -q "sdbb1" "$w/log" && wrote; } \
  && ok "only the target's own mounted partitions are unmounted" || bad "prefix: rc=$rc log=$(cat "$w/log")"

# 9. Typing the root's own dm device (not the disk under it) is refused too.
setup; echo "$w/dev/mapper/root" > "$w/st/rootsrc"; mkdir -p "$w/sys/dm-0"; : > "$w/dev/dm-0"
ln -sf ../dm-0 "$w/dev/mapper/root"
printf 'dm-0 crypt\nnvme0n1p1 part\nnvme0n1 disk\n' > "$w/st/lsblk-root"
out=$(run "$w/dev/mapper/root"); rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -qi "root"; } \
  && ok "the root's own dm device is refused" || bad "dm device: rc=$rc out=[$out]"

# 10. A btrfs-subvolume root (findmnt SOURCE carries [/@]) still protects its disk.
setup; out=$(run "$w/dev/sda"); rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -qi "root"; } \
  && ok "a btrfs subvolume root still protects its disk" || bad "btrfs: rc=$rc out=[$out]"

# 11. A /dev root that cannot be resolved stops the run instead of dropping the guard.
setup; echo "/dev/root" > "$w/st/rootsrc"; out=$(run "$w/dev/sdb"); rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -qi "root"; } \
  && ok "an unresolvable /dev root fails closed" || bad "unresolvable root: rc=$rc out=[$out]"

# 12. Swap on the target is turned off, not treated as a failed unmount.
setup; echo "$w/dev/sdb1 [SWAP]" > "$w/st/mounts"; out=$(run "$w/dev/sdb"); rc=$?
{ [ $rc -eq 0 ] && grep -q "^swapoff $w/dev/sdb1" "$w/log" && ! grep -q "^umount" "$w/log" && wrote; } \
  && ok "a swap partition on the target is swapped off" || bad "swap: rc=$rc out=[$out] log=$(cat "$w/log")"

# 13. A partition still in use where this script cannot see the mount (the host,
#     from inside the SDK container) makes the kernel refuse a table re-read;
#     that stops the run before dd.
setup; : > "$w/st/busy"; out=$(run "$w/dev/sdb"); rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -qi "in use"; } \
  && ok "a target busy outside this mount namespace is refused" || bad "busy elsewhere: rc=$rc out=[$out]"

# 14. The device list reads the provided sysfs and hides the root disk.
setup; out=$(run "$w/dev/sdb"); rc=$?
{ echo "$out" | grep -q "/dev/sdb " && ! echo "$out" | grep -q "/dev/sda " ; } \
  && ok "the device list shows the stick and hides the root disk" || bad "listing: out=[$out]"

# 15. A whole block device that is not a disk (a data volume on dm, an md
#     array, a loop device) is refused: it has no partition file and is not
#     under /, but writing a disk image onto it destroys a volume.
setup; mkdir -p "$w/sys/dm-3"; : > "$w/dev/dm-3"; ln -s ../dm-3 "$w/dev/mapper/data"; echo lvm > "$w/st/type-dm-3"
out=$(run "$w/dev/mapper/data"); rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -qi "not a disk"; } \
  && ok "a dm data volume is refused as a target" || bad "non-disk: rc=$rc out=[$out]"

# 16. Without lsblk (the x86 SDK container shipped none) every guard that reads
#     it would misreport the target, so the run stops up front and names it.
#     PATH holds bash and the stubs other than lsblk, nothing from the host.
setup; mkdir -p "$w/nolsblk"; ln -sf "$(command -v bash)" "$w/nolsblk/bash"
for t in "$w/bin/"*; do [ "${t##*/}" = lsblk ] || ln -sf "$t" "$w/nolsblk/"; done
: > "$w/log"; out=$(printf '%s\nyes\n' "$w/dev/sdb" | PATH="$w/nolsblk" AVOCADO_PROVISION_SYSBLOCK="$w/sys" \
  AVOCADO_STONE_MANIFEST="$w/manifest.json" AVOCADO_STONE_DATA_DIR="$w" AVOCADO_STONE_BUILD_DIR="$w/build" \
  bash "$script" 2>&1); rc=$?
{ [ $rc -ne 0 ] && ! wrote && echo "$out" | grep -q "lsblk not found"; } \
  && ok "a missing lsblk stops the run before any check or write" || bad "no lsblk: rc=$rc out=[$out]"
echo
echo "passed: $pass  failed: $fail  (checks: $((pass + fail))/16 run)"
[ "$fail" -eq 0 ] && [ $((pass + fail)) -eq 16 ]
