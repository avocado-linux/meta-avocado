#!/usr/bin/env bash
# Host test with a stateful efibootmgr stub and a fake /sys, /dev and efivars
# tree. The disk mirrors the R8000's NVRAM as found on 2026-09-24: firmware had
# made only a PXE entry and a removable-media 'UEFI OS' entry, and nothing
# carried the boot-a/boot-b labels avocadoctl's efibootmgr slot action looks up.
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts, so bad runs only when the check failed
set -u
here=$(cd "$(dirname "$0")" && pwd)
script=$here/../files/avocado-efi-slot-entries
w=$(mktemp -d)
trap 'rm -rf "$w"' EXIT
pass=0
fail=0
ok() {
  echo "  ok   - $1"
  pass=$((pass + 1))
}
bad() {
  echo "  FAIL - $1"
  fail=$((fail + 1))
}

UA=a2e0a8c1-0004-4b01-a000-000000000001
UB=a2e0a8c1-0004-4b01-b000-000000000001
LOADER_GUID=4a67b082-0a4c-41cf-b6c7-440b29bb8c4f

setup() {
  rm -rf "${w:?}/dev" "${w:?}/sys" "${w:?}/efivars" "${w:?}/nv"
  mkdir -p "$w/bin" "$w/dev/disk/by-partuuid" "$w/efivars" "$w/nv"
  # sda: boot-a (1), boot-b (2), recovery (3); nvme0n1p1 carries a stray boot-a
  # label, which must never be picked up - it is not the disk that booted.
  for spec in sda:1:boot-a:$UA sda:2:boot-b:$UB sda:3:recovery:c0ffee00-0000-0000-0000-000000000003 \
    nvme0n1:1:boot-a:deadbeef-0000-0000-0000-000000000001; do
    disk=${spec%%:*}
    rest=${spec#*:}
    n=${rest%%:*}
    rest=${rest#*:}
    name=${rest%%:*}
    uuid=${rest#*:}
    case $disk in nvme*) p=${disk}p$n ;; *) p=$disk$n ;; esac
    mkdir -p "$w/sys/$disk/$p"
    echo "$n" >"$w/sys/$disk/$p/partition"
    printf 'DEVNAME=%s\nPARTN=%s\nPARTNAME=%s\nPARTUUID=%s\n' "$p" "$n" "$name" "$uuid" >"$w/sys/$disk/$p/uevent"
    ln -s "$disk/$p" "$w/sys/$p"
    : >"$w/dev/$disk"
    : >"$w/dev/$p"
    ln -s "../../$p" "$w/dev/disk/by-partuuid/$uuid"
  done
  # efivarfs: 4 attribute bytes, then the UTF-16LE string systemd-boot wrote
  # (upper case, as systemd-boot writes it).
  {
    printf '\x06\x00\x00\x00'
    printf '%s' "${UA^^}" | sed 's/./&\x00/g'
    printf '\x00\x00'
  } \
    >"$w/efivars/LoaderDevicePartUUID-$LOADER_GUID"
  printf '0002|UEFI: PXE IPv4 Intel(R) Ethernet Controller I226-IT|PciRoot(0x0)/Pci(0x2,0x1)/MAC(d063b407746c,0)/IPv4(0.0.0.0)\n0003|UEFI OS|HD(1,GPT,%s,0x800,0x80000)/File(\\EFI\\BOOT\\BOOTX64.EFI)\n' "${UA^^}" >"$w/nv/entries"
  echo 0002,0003 >"$w/nv/order"
}

# efibootmgr stub: -v lists, -c creates and prepends to BootOrder, -C creates
# and leaves BootOrder alone (both as the real tool does), -b N -B deletes, -o
# sets the order, -n sets BootNext. Every call is logged. STUB_FAIL_DELETE=<num>
# makes deleting that one entry fail, as an NVRAM write error would. STUB_FAIL=1 makes every call fail.
mkdir -p "$w/bin"
cat >"$w/bin/efibootmgr" <<S
#!/bin/bash
nv="$w/nv"; echo "efibootmgr \$*" >> "$w/log"
flock -n "$w/lock/efi-nvram.lock" true 2>/dev/null && echo "UNLOCKED efibootmgr \$*" >> "$w/log"
[ "\${STUB_FAIL:-0}" = 1 ] && { echo "efibootmgr: EFI variables are not supported" >&2; exit 2; }
args=("\$@"); disk=; part=; label=; loader=; num=; del=0; order=; prepend=; next=
for ((i=0;i<\${#args[@]};i++)); do case "\${args[i]}" in
  -d) disk=\${args[i+1]} ;; -p) part=\${args[i+1]} ;; -L) label=\${args[i+1]} ;; -l) loader=\${args[i+1]} ;;
  -b) num=\${args[i+1]} ;; -B) del=1 ;; -o) order=\${args[i+1]} ;; -c) prepend=1 ;; -n) next=\${args[i+1]} ;; esac; done
if [ -n "\$label" ]; then
  n=\$(printf '%04X' \$(( 16#\$(cut -d'|' -f1 "\$nv/entries" | sort | tail -1) + 1 )))
  d=\$(basename "\$disk"); case \$d in nvme*) p=\${d}p\$part ;; *) p=\$d\$part ;; esac
  u=; for l in "$w/dev/disk/by-partuuid/"*; do [ "\$(readlink -f "\$l")" = "\$(readlink -f "$w/dev/\$p")" ] && u=\$(basename "\$l"); done
  printf '%s|%s|HD(%s,GPT,%s,0x800,0x80000)/File(%s)\n' "\$n" "\$label" "\$part" "\$u" "\$loader" >> "\$nv/entries"
  [ -n "\$prepend" ] && echo "\$n,\$(cat "\$nv/order")" > "\$nv/order"; exit 0
fi
if [ "\$del" = 1 ]; then
  [ "\$num" = "\${STUB_FAIL_DELETE:-}" ] && { echo "efibootmgr: Could not delete Boot\$num" >&2; exit 5; }
  grep -v "^\$num|" "\$nv/entries" > "\$nv/e.tmp"; mv "\$nv/e.tmp" "\$nv/entries"
  tr ',' '\n' < "\$nv/order" | grep -vx "\$num" | paste -sd, > "\$nv/o.tmp"; mv "\$nv/o.tmp" "\$nv/order"; exit 0
fi
if [ -n "\$order" ]; then echo "\$order" > "\$nv/order"; exit 0; fi
if [ -n "\$next" ]; then echo "\$next" > "\$nv/next"; exit 0; fi
[ -s "\$nv/next" ] && echo "BootNext: \$(cat "\$nv/next")"
echo "BootCurrent: 0003"; echo "BootOrder: \$(cat "\$nv/order")"
while IFS='|' read -r n l p; do printf 'Boot%s* %s\t%s\n' "\$n" "\$l" "\$p"; done < "\$nv/entries"
S
chmod +x "$w/bin/efibootmgr"

run() {
  : >"$w/log"
  PATH="$w/bin:$PATH" AVOCADO_EFI_SLOTS_LOCK="$w/lock/efi-nvram.lock" AVOCADO_EFI_SLOTS_LOCK_WAIT="${LOCK_WAIT:-30}" AVOCADO_EFI_SLOTS_NO_SETTLE=1 AVOCADO_EFI_SLOTS_EFIVARS="$w/efivars" AVOCADO_EFI_SLOTS_DEVDIR="$w/dev" AVOCADO_EFI_SLOTS_SYSBLOCK="$w/sys" sh "$script" 2>&1
}
num_of() { awk -F'|' -v l="$1" '$2==l{print $1}' "$w/nv/entries"; }
writes() { grep -cE 'efibootmgr .*(-c|-C|-B|-o|-n)( |$)' "$w/log"; }
set_booted() { {
  printf '\x06\x00\x00\x00'
  printf '%s' "${1^^}" | sed 's/./&\x00/g'
  printf '\x00\x00'
} \
  >"$w/efivars/LoaderDevicePartUUID-$LOADER_GUID"; }

# 1. First boot on the R8000's NVRAM: both slots created on the booted disk,
#    on the right partitions, ahead of PXE and the removable fallback.
setup
out=$(run)
rc=$?
a=$(num_of boot-a)
b=$(num_of boot-b)
{ [ $rc -eq 0 ] \
  && grep -q "^$a|boot-a|HD(1,GPT,$UA," "$w/nv/entries" \
  && grep -q "^$b|boot-b|HD(2,GPT,$UB," "$w/nv/entries" \
  && grep -q "efibootmgr .*-C -d $w/dev/sda -p 1 -L boot-a" "$w/log" \
  && ! grep -q "efibootmgr .* -c " "$w/log" \
  && grep -q "efibootmgr .*-d $w/dev/sda -p 2 -L boot-b" "$w/log" \
  && [ "$(cat "$w/nv/order")" = "$a,$b,0002,0003" ]; } \
  && ok "first boot creates boot-a/boot-b on sda1/sda2 and orders them ahead of PXE and 'UEFI OS'" \
  || bad "first boot: rc=$rc out=[$out] order=$(cat "$w/nv/order") entries=$(cat "$w/nv/entries")"

# 2. A second run changes nothing in NVRAM.
order_before=$(cat "$w/nv/order")
out=$(run)
rc=$?
{ [ $rc -eq 0 ] && [ "$(writes)" -eq 0 ] && [ "$(cat "$w/nv/order")" = "$order_before" ]; } \
  && ok "entries already correct: no NVRAM writes, BootOrder untouched" \
  || bad "idempotent: rc=$rc writes=$(writes) log=$(cat "$w/log")"

# 3. The existing order is left alone when nothing had to be created, even if
#    the other slot currently comes first - reordering on every boot would make
#    a BootNext trial of a new slot permanent before it was verified.
echo "$b,$a,0002,0003" >"$w/nv/order"
out=$(run)
rc=$?
{ [ $rc -eq 0 ] && [ "$(writes)" -eq 0 ] && [ "$(cat "$w/nv/order")" = "$b,$a,0002,0003" ]; } \
  && ok "a correct pair is never reordered" || bad "reorder: rc=$rc order=$(cat "$w/nv/order") log=$(cat "$w/log")"

# 4. A boot-b entry that points at another partition is replaced, and the
#    replacement exists before the stale one goes, so a failure in between
#    never leaves the slot with no entry. Test 3 left boot-b first; replacing
#    an entry puts the booted slot (A) back ahead of the other one.
sed -i "s/^$b|boot-b|HD(2,GPT,$UB,/$b|boot-b|HD(9,GPT,deadbeef-0000-0000-0000-000000000009,/" "$w/nv/entries"
out=$(run)
rc=$?
nb=$(num_of boot-b)
{ [ $rc -eq 0 ] && grep -q "efibootmgr .*-b $b -B" "$w/log" && grep -q "^$nb|boot-b|HD(2,GPT,$UB," "$w/nv/entries" \
  && [ "$(grep -n -- '-L boot-b' "$w/log" | cut -d: -f1)" -lt "$(grep -n -- "-b $b -B" "$w/log" | cut -d: -f1)" ] \
  && [ "$(grep -c '|boot-b|' "$w/nv/entries")" -eq 1 ] && [ "$(num_of boot-a)" = "$a" ] \
  && [ "$(cat "$w/nv/order")" = "$a,$nb,0002,0003" ]; } \
  && ok "a stale boot-b is replaced on sda2 (created before the delete), booted slot first" \
  || bad "stale: log=$(cat "$w/log") entries=$(cat "$w/nv/entries")"

# 5. Not booted through systemd-boot: nothing to anchor on, nothing written.
setup
rm "$w/efivars/LoaderDevicePartUUID-$LOADER_GUID"
out=$(run)
rc=$?
{ [ $rc -eq 0 ] && [ ! -s "$w/log" ] && echo "$out" | grep -q "LoaderDevicePartUUID"; } \
  && ok "without LoaderDevicePartUUID it exits 0 and touches nothing" || bad "no-var: rc=$rc out=$out log=$(cat "$w/log")"

# 6. A slot partition missing from the booted disk is skipped; the stray boot-a
#    label on the NVMe is never used in its place.
setup
rm "$w/sys/sda1" "$w/dev/disk/by-partuuid/$UA"
rm -rf "$w/sys/sda/sda1"
# keep the booted ESP resolvable: point the loader variable at boot-b instead
set_booted "$UB"
out=$(run)
rc=$?
{ [ $rc -eq 0 ] && ! grep -q -- "-L boot-a" "$w/log" && grep -q "efibootmgr .*-d $w/dev/sda -p 2 -L boot-b" "$w/log" \
  && echo "$out" | grep -q "boot-a"; } \
  && ok "a slot missing on the booted disk is skipped, never taken from another disk" \
  || bad "missing slot: rc=$rc out=$out log=$(cat "$w/log")"

# 7. A device that committed slot B loses its entries (firmware reset). The
#    recreated pair puts the running slot first; boot-a first would send it
#    back to the slot it moved away from.
setup
set_booted "$UB"
out=$(run)
rc=$?
a=$(num_of boot-a)
b=$(num_of boot-b)
{ [ $rc -eq 0 ] && [ -n "$a" ] && [ -n "$b" ] && [ "$(cat "$w/nv/order")" = "$b,$a,0002,0003" ]; } \
  && ok "booted from slot B: recreated entries order boot-b ahead of boot-a" \
  || bad "booted B: rc=$rc out=[$out] order=$(cat "$w/nv/order") entries=$(cat "$w/nv/entries")"

# 8. Duplicate labels: two correct boot-a entries and one pointing elsewhere.
#    One correct entry survives, the rest go, and nothing is created.
setup
printf '0004|boot-a|HD(1,GPT,%s,0x800,0x80000)/File(x)\n0005|boot-a|HD(9,GPT,deadbeef-0000-0000-0000-000000000009,0x800,0x80000)/File(x)\n0006|boot-a|HD(1,GPT,%s,0x800,0x80000)/File(x)\n0007|boot-b|HD(2,GPT,%s,0x800,0x80000)/File(x)\n' \
  "$UA" "$UA" "$UB" >>"$w/nv/entries"
echo 0004,0005,0006,0007,0002,0003 >"$w/nv/order"
out=$(run)
rc=$?
{ [ $rc -eq 0 ] && [ "$(num_of boot-a)" = 0004 ] && ! grep -qE -- ' -[cC] ' "$w/log" \
  && grep -q -- "-b 0005 -B" "$w/log" && grep -q -- "-b 0006 -B" "$w/log" \
  && [ "$(cat "$w/nv/order")" = 0004,0007,0002,0003 ]; } \
  && ok "duplicate boot-a entries collapse to the first correct one, without a reorder" \
  || bad "duplicates: rc=$rc out=[$out] log=$(cat "$w/log") entries=$(cat "$w/nv/entries")"

# 9. efibootmgr cannot read NVRAM: fail loudly and write nothing, rather than
#    reading an empty listing as "no slots" and creating duplicates.
setup
: >"$w/log"
out=$(STUB_FAIL=1 run)
rc=$?
{ [ $rc -ne 0 ] && [ "$(writes)" -eq 0 ] && echo "$out" | grep -q "efibootmgr -v failed"; } \
  && ok "a failed efibootmgr read exits non-zero with no NVRAM writes" \
  || bad "efibootmgr failure: rc=$rc out=[$out] log=$(cat "$w/log")"

# 10. The duplicate firmware will try is the one kept: boot-a exists as 0004
#     (not in BootOrder) and 0006 (in it). Deleting 0006 would drop slot A out
#     of BootOrder altogether.
setup
printf '0004|boot-a|HD(1,GPT,%s,0x800,0x80000)/File(x)\n0006|boot-a|HD(1,GPT,%s,0x800,0x80000)/File(x)\n0007|boot-b|HD(2,GPT,%s,0x800,0x80000)/File(x)\n' \
  "$UA" "$UA" "$UB" >>"$w/nv/entries"
echo 0006,0007,0002,0003 >"$w/nv/order"
out=$(run)
rc=$?
{ [ $rc -eq 0 ] && [ "$(num_of boot-a)" = 0006 ] && grep -q -- "-b 0004 -B" "$w/log" \
  && [ "$(cat "$w/nv/order")" = 0006,0007,0002,0003 ] && ! grep -q -- ' -o ' "$w/log"; } \
  && ok "of two good duplicates the one in BootOrder is kept, and BootOrder is untouched" \
  || bad "dup in order: rc=$rc log=$(cat "$w/log") order=$(cat "$w/nv/order")"

# 11. Failed trial of slot B, rolled back without a reboot: B is running,
#     BootNext names a stale boot-a, BootOrder still starts with it. The stale
#     entry is replaced in place and BootNext follows it; B is never promoted.
setup
set_booted "$UB"
printf '0004|boot-a|HD(9,GPT,deadbeef-0000-0000-0000-000000000009,0x800,0x80000)/File(x)\n0005|boot-b|HD(2,GPT,%s,0x800,0x80000)/File(x)\n' "$UB" >>"$w/nv/entries"
echo 0004,0005,0002,0003 >"$w/nv/order"
echo 0004 >"$w/nv/next"
out=$(run)
rc=$?
na=$(num_of boot-a)
{ [ $rc -eq 0 ] && [ -n "$na" ] && [ "$na" != 0004 ] && [ "$(cat "$w/nv/order")" = "$na,0005,0002,0003" ] \
  && [ "$(cat "$w/nv/next")" = "$na" ]; } \
  && ok "a rollback's stale BootNext target is replaced in place; the failed slot stays second" \
  || bad "failed trial: rc=$rc out=[$out] order=$(cat "$w/nv/order") next=$(cat "$w/nv/next" 2>/dev/null) entries=$(cat "$w/nv/entries")"

# 12. A correct entry firmware dropped from BootOrder is put back next to the
#     other slot, not ahead of it.
setup
printf '0004|boot-a|HD(1,GPT,%s,0x800,0x80000)/File(x)\n0005|boot-b|HD(2,GPT,%s,0x800,0x80000)/File(x)\n' "$UA" "$UB" >>"$w/nv/entries"
echo 0005,0002,0003 >"$w/nv/order"
out=$(run)
rc=$?
{ [ $rc -eq 0 ] && [ "$(cat "$w/nv/order")" = 0005,0004,0002,0003 ] && ! grep -qE -- ' -[cCB] ' "$w/log"; } \
  && ok "a slot missing from BootOrder is re-added after the other slot" \
  || bad "re-add: rc=$rc log=$(cat "$w/log") order=$(cat "$w/nv/order")"

# 13. An NVRAM write failing part-way must not leave BootNext or BootOrder
#     naming a deleted entry. BootNext targets a stale boot-a that is
#     replaced; deleting a stale boot-b duplicate afterwards fails and aborts
#     the run. BootNext and both BootOrder slots must already be on the kept
#     entries by then (0006 hands its place to 0005 before its delete).
setup
set_booted "$UB"
printf '0004|boot-a|HD(9,GPT,deadbeef-0000-0000-0000-000000000009,0x800,0x80000)/File(x)\n0005|boot-b|HD(2,GPT,%s,0x800,0x80000)/File(x)\n0006|boot-b|HD(8,GPT,deadbeef-0000-0000-0000-000000000008,0x800,0x80000)/File(x)\n' "$UB" >>"$w/nv/entries"
echo 0004,0005,0006,0002,0003 >"$w/nv/order"
echo 0004 >"$w/nv/next"
out=$(STUB_FAIL_DELETE=0006 run)
rc=$?
na=$(num_of boot-a)
{ [ $rc -ne 0 ] && [ -n "$na" ] && [ "$na" != 0004 ] && ! grep -q '^0004|' "$w/nv/entries" \
  && [ "$(cat "$w/nv/next")" = "$na" ] && [ "$(cat "$w/nv/order")" = "$na,0005,0002,0003" ]; } \
  && ok "a failed delete part-way leaves BootNext and BootOrder on the replacement entry" \
  || bad "partial write: rc=$rc out=[$out] order=$(cat "$w/nv/order") next=$(cat "$w/nv/next" 2>/dev/null) entries=$(cat "$w/nv/entries")"

# 14. A second disk flashed from the same image (a USB stick being prepared)
#     carries the same partition UUIDs. udev's by-partuuid link may name
#     either disk and firmware cannot tell them apart, so nothing is written
#     and the unit fails - even when the link happens to name the clone.
setup
for n in 1 2; do
  mkdir -p "$w/sys/sdb/sdb$n"
  echo "$n" >"$w/sys/sdb/sdb$n/partition"
  u=$UA; l=boot-a; [ "$n" = 2 ] && { u=$UB; l=boot-b; }
  printf 'DEVNAME=sdb%s\nPARTN=%s\nPARTNAME=%s\nPARTUUID=%s\n' "$n" "$n" "$l" "$u" >"$w/sys/sdb/sdb$n/uevent"
  ln -s "sdb/sdb$n" "$w/sys/sdb$n"
  : >"$w/dev/sdb$n"
  ln -sfn "../../sdb$n" "$w/dev/disk/by-partuuid/$u"
done
: >"$w/dev/sdb"
before=$(cat "$w/nv/entries" "$w/nv/order")
out=$(run)
rc=$?
{ [ $rc -ne 0 ] && [ "$(writes)" -eq 0 ] && [ "$(cat "$w/nv/entries" "$w/nv/order")" = "$before" ] && echo "$out" | grep -qi "more than one"; } \
  && ok "a cloned disk with the same partition UUIDs stops the run before any NVRAM write" \
  || bad "clone: rc=$rc writes=$(writes) out=[$out] entries=$(cat "$w/nv/entries")"

# 15. Only the other slot's UUID is duplicated: still nothing is written.
setup
mkdir -p "$w/sys/sdb/sdb2"
echo 2 >"$w/sys/sdb/sdb2/partition"
printf 'DEVNAME=sdb2\nPARTN=2\nPARTNAME=boot-b\nPARTUUID=%s\n' "$UB" >"$w/sys/sdb/sdb2/uevent"
ln -s sdb/sdb2 "$w/sys/sdb2"
: >"$w/dev/sdb2"
out=$(run)
rc=$?
{ [ $rc -ne 0 ] && [ "$(writes)" -eq 0 ] && echo "$out" | grep -qi "more than one"; } \
  && ok "a duplicated slot UUID alone also stops the run before any NVRAM write" \
  || bad "slot clone: rc=$rc writes=$(writes) out=[$out]"

# 16. After a reflash both slot entries are stale, and the stale boot-b sat
#     ahead of the stale boot-a. Each replacement takes its predecessor's
#     place, which would leave boot-b ahead: once firmware drops its own entry
#     (the R8000's AMI does at POST) a plain reboot lands on slot B. The booted
#     slot's entry is put ahead of the other slot's; nothing else moves.
setup
printf '0000|boot-b|HD(2,GPT,dead0000-0000-0000-0000-00000000000b,0x80800,0x80000)/File(x)\n0001|boot-a|HD(1,GPT,dead0000-0000-0000-0000-00000000000a,0x800,0x80000)/File(x)\n' >>"$w/nv/entries"
echo 0003,0002,0000,0001 >"$w/nv/order"
out=$(run)
rc=$?
a=$(num_of boot-a)
b=$(num_of boot-b)
{ [ $rc -eq 0 ] && [ -n "$a" ] && [ -n "$b" ] && [ "$(cat "$w/nv/order")" = "0003,0002,$a,$b" ]; } \
  && ok "replacing stale entries puts the booted slot ahead of the other, in place" \
  || bad "reflash order: rc=$rc out=[$out] order=$(cat "$w/nv/order") entries=$(cat "$w/nv/entries")"

# 17. Every efibootmgr call, reads included, runs under the NVRAM lock that
#     avocadoctl's slot action also takes. The stub logs any call it can lock
#     the file itself for.
setup
out=$(run)
rc=$?
{ [ $rc -eq 0 ] && [ "$(writes)" -gt 0 ] && ! grep -q '^UNLOCKED' "$w/log"; } \
  && ok "every efibootmgr call holds /run/avocado/efi-nvram.lock" \
  || bad "lock: rc=$rc log=$(cat "$w/log")"

# 18. A lock held elsewhere delays the repair by the bounded wait, then it goes
#     ahead: a wedged avocadoctl must not keep the slot entries broken.
setup
mkdir -p "$w/lock"
flock "$w/lock/efi-nvram.lock" sleep 10 &
holder=$!
sleep 0.3
out=$(LOCK_WAIT=1 run)
rc=$?
kill "$holder" 2>/dev/null
wait "$holder" 2>/dev/null
{ [ $rc -eq 0 ] && [ -n "$(num_of boot-a)" ] && [ -n "$(num_of boot-b)" ] \
  && printf '%s\n' "$out" | grep -q 'held elsewhere, continuing without it'; } \
  && ok "a lock held elsewhere times out and the entries are still repaired" \
  || bad "held lock: rc=$rc out=[$out] entries=$(cat "$w/nv/entries")"

echo
echo "passed: $pass  failed: $fail  (checks: $((pass + fail))/18 run)"
[ "$fail" -eq 0 ] && [ $((pass + fail)) -eq 18 ]
