#!/usr/bin/env bash
# Host test with a stateful efibootmgr stub and a fake /sys, /dev and efivars
# tree. The disk mirrors the R8000's NVRAM as found on 2026-09-24: firmware had
# made only a PXE entry and a removable-media 'UEFI OS' entry, and nothing
# carried the boot-a/boot-b labels avocadoctl's efibootmgr slot action looks up.
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts, so bad runs only when the check failed
set -u
here=$(cd "$(dirname "$0")" && pwd); script=$here/../files/avocado-efi-slot-entries
w=$(mktemp -d); trap 'rm -rf "$w"' EXIT
pass=0; fail=0; ok(){ echo "  ok   - $1"; pass=$((pass+1)); }; bad(){ echo "  FAIL - $1"; fail=$((fail+1)); }

UA=a2e0a8c1-0003-4b01-a000-000000000001
UB=a2e0a8c1-0003-4b01-b000-000000000001
LOADER_GUID=4a67b082-0a4c-41cf-b6c7-440b29bb8c4f

setup() {
  rm -rf "${w:?}/dev" "${w:?}/sys" "${w:?}/efivars" "${w:?}/nv"; mkdir -p "$w/bin" "$w/dev/disk/by-partuuid" "$w/efivars" "$w/nv"
  # sda: boot-a (1), boot-b (2), recovery (3); nvme0n1p1 carries a stray boot-a
  # label, which must never be picked up - it is not the disk that booted.
  for spec in sda:1:boot-a:$UA sda:2:boot-b:$UB sda:3:recovery:c0ffee00-0000-0000-0000-000000000003 \
              nvme0n1:1:boot-a:deadbeef-0000-0000-0000-000000000001; do
    disk=${spec%%:*}; rest=${spec#*:}; n=${rest%%:*}; rest=${rest#*:}; name=${rest%%:*}; uuid=${rest#*:}
    case $disk in nvme*) p=${disk}p$n ;; *) p=$disk$n ;; esac
    mkdir -p "$w/sys/$disk/$p"; echo "$n" > "$w/sys/$disk/$p/partition"
    printf 'DEVNAME=%s\nPARTN=%s\nPARTNAME=%s\n' "$p" "$n" "$name" > "$w/sys/$disk/$p/uevent"
    ln -s "$disk/$p" "$w/sys/$p"; : > "$w/dev/$disk"; : > "$w/dev/$p"
    ln -s "../../$p" "$w/dev/disk/by-partuuid/$uuid"
  done
  # efivarfs: 4 attribute bytes, then the UTF-16LE string systemd-boot wrote
  # (upper case, as systemd-boot writes it).
  { printf '\x06\x00\x00\x00'; printf '%s' "${UA^^}" | sed 's/./&\x00/g'; printf '\x00\x00'; } \
    > "$w/efivars/LoaderDevicePartUUID-$LOADER_GUID"
  printf '0002|UEFI: PXE IPv4 Intel(R) Ethernet Controller I226-IT|PciRoot(0x0)/Pci(0x2,0x1)/MAC(d063b407746c,0)/IPv4(0.0.0.0)\n0003|UEFI OS|HD(1,GPT,%s,0x800,0x80000)/File(\\EFI\\BOOT\\BOOTX64.EFI)\n' "${UA^^}" > "$w/nv/entries"
  echo 0002,0003 > "$w/nv/order"
}

# efibootmgr stub: -v lists, -c creates (prepending to BootOrder like the real
# tool), -b N -B deletes, -o sets the order. Every call is logged.
mkdir -p "$w/bin"
cat > "$w/bin/efibootmgr" <<S
#!/bin/bash
nv="$w/nv"; echo "efibootmgr \$*" >> "$w/log"
args=("\$@"); disk=; part=; label=; loader=; num=; del=0; order=
for ((i=0;i<\${#args[@]};i++)); do case "\${args[i]}" in
  -d) disk=\${args[i+1]} ;; -p) part=\${args[i+1]} ;; -L) label=\${args[i+1]} ;; -l) loader=\${args[i+1]} ;;
  -b) num=\${args[i+1]} ;; -B) del=1 ;; -o) order=\${args[i+1]} ;; esac; done
if [ -n "\$label" ]; then
  n=\$(printf '%04X' \$(( 16#\$(cut -d'|' -f1 "\$nv/entries" | sort | tail -1) + 1 )))
  d=\$(basename "\$disk"); case \$d in nvme*) p=\${d}p\$part ;; *) p=\$d\$part ;; esac
  u=; for l in "$w/dev/disk/by-partuuid/"*; do [ "\$(readlink -f "\$l")" = "\$(readlink -f "$w/dev/\$p")" ] && u=\$(basename "\$l"); done
  printf '%s|%s|HD(%s,GPT,%s,0x800,0x80000)/File(%s)\n' "\$n" "\$label" "\$part" "\$u" "\$loader" >> "\$nv/entries"
  echo "\$n,\$(cat "\$nv/order")" > "\$nv/order"; exit 0
fi
if [ "\$del" = 1 ]; then
  grep -v "^\$num|" "\$nv/entries" > "\$nv/e.tmp"; mv "\$nv/e.tmp" "\$nv/entries"
  tr ',' '\n' < "\$nv/order" | grep -vx "\$num" | paste -sd, > "\$nv/o.tmp"; mv "\$nv/o.tmp" "\$nv/order"; exit 0
fi
if [ -n "\$order" ]; then echo "\$order" > "\$nv/order"; exit 0; fi
echo "BootCurrent: 0003"; echo "BootOrder: \$(cat "\$nv/order")"
while IFS='|' read -r n l p; do printf 'Boot%s* %s\t%s\n' "\$n" "\$l" "\$p"; done < "\$nv/entries"
S
chmod +x "$w/bin/efibootmgr"

run(){ : > "$w/log"; PATH="$w/bin:$PATH" AVOCADO_EFI_SLOTS_EFIVARS="$w/efivars" AVOCADO_EFI_SLOTS_DEVDIR="$w/dev" AVOCADO_EFI_SLOTS_SYSBLOCK="$w/sys" sh "$script" 2>&1; }
num_of(){ awk -F'|' -v l="$1" '$2==l{print $1}' "$w/nv/entries"; }
writes(){ grep -cE 'efibootmgr .*(-c|-B|-o)( |$)' "$w/log"; }

# 1. First boot on the R8000's NVRAM: both slots created on the booted disk,
#    on the right partitions, ahead of PXE and the removable fallback.
setup; out=$(run); rc=$?
a=$(num_of boot-a); b=$(num_of boot-b)
{ [ $rc -eq 0 ] \
  && grep -q "^$a|boot-a|HD(1,GPT,$UA," "$w/nv/entries" \
  && grep -q "^$b|boot-b|HD(2,GPT,$UB," "$w/nv/entries" \
  && grep -q "efibootmgr .*-d $w/dev/sda -p 1 -L boot-a" "$w/log" \
  && grep -q "efibootmgr .*-d $w/dev/sda -p 2 -L boot-b" "$w/log" \
  && [ "$(cat "$w/nv/order")" = "$a,$b,0002,0003" ]; } \
  && ok "first boot creates boot-a/boot-b on sda1/sda2 and orders them ahead of PXE and 'UEFI OS'" \
  || bad "first boot: rc=$rc out=[$out] order=$(cat "$w/nv/order") entries=$(cat "$w/nv/entries")"

# 2. A second run changes nothing in NVRAM.
order_before=$(cat "$w/nv/order"); out=$(run); rc=$?
{ [ $rc -eq 0 ] && [ "$(writes)" -eq 0 ] && [ "$(cat "$w/nv/order")" = "$order_before" ]; } \
  && ok "entries already correct: no NVRAM writes, BootOrder untouched" \
  || bad "idempotent: rc=$rc writes=$(writes) log=$(cat "$w/log")"

# 3. The existing order is left alone when nothing had to be created, even if
#    the other slot currently comes first - reordering on every boot would make
#    a BootNext trial of a new slot permanent before it was verified.
echo "$b,$a,0002,0003" > "$w/nv/order"; out=$(run)
{ [ "$(writes)" -eq 0 ] && [ "$(cat "$w/nv/order")" = "$b,$a,0002,0003" ]; } \
  && ok "a correct pair is never reordered" || bad "reorder: order=$(cat "$w/nv/order") log=$(cat "$w/log")"

# 4. A boot-b entry that points at another partition is replaced.
sed -i "s/^$b|boot-b|HD(2,GPT,$UB,/$b|boot-b|HD(9,GPT,deadbeef-0000-0000-0000-000000000009,/" "$w/nv/entries"
out=$(run); nb=$(num_of boot-b)
{ grep -q "efibootmgr .*-b $b -B" "$w/log" && grep -q "^$nb|boot-b|HD(2,GPT,$UB," "$w/nv/entries" \
  && [ "$(grep -c '|boot-b|' "$w/nv/entries")" -eq 1 ] && [ "$(num_of boot-a)" = "$a" ]; } \
  && ok "a stale boot-b is deleted and recreated on sda2, boot-a untouched" \
  || bad "stale: log=$(cat "$w/log") entries=$(cat "$w/nv/entries")"

# 5. Not booted through systemd-boot: nothing to anchor on, nothing written.
setup; rm "$w/efivars/LoaderDevicePartUUID-$LOADER_GUID"; out=$(run); rc=$?
{ [ $rc -eq 0 ] && [ ! -s "$w/log" ] && echo "$out" | grep -q "LoaderDevicePartUUID"; } \
  && ok "without LoaderDevicePartUUID it exits 0 and touches nothing" || bad "no-var: rc=$rc out=$out log=$(cat "$w/log")"

# 6. A slot partition missing from the booted disk is skipped; the stray boot-a
#    label on the NVMe is never used in its place.
setup; rm "$w/sys/sda1" "$w/dev/disk/by-partuuid/$UA"; rm -rf "$w/sys/sda/sda1"
# keep the booted ESP resolvable: point the loader variable at boot-b instead
{ printf '\x06\x00\x00\x00'; printf '%s' "${UB^^}" | sed 's/./&\x00/g'; printf '\x00\x00'; } \
  > "$w/efivars/LoaderDevicePartUUID-$LOADER_GUID"
out=$(run); rc=$?
{ [ $rc -eq 0 ] && ! grep -q -- "-L boot-a" "$w/log" && grep -q "efibootmgr .*-d $w/dev/sda -p 2 -L boot-b" "$w/log" \
  && echo "$out" | grep -q "boot-a"; } \
  && ok "a slot missing on the booted disk is skipped, never taken from another disk" \
  || bad "missing slot: rc=$rc out=$out log=$(cat "$w/log")"

echo; echo "passed: $pass  failed: $fail  (checks: $((pass+fail))/6 run)"; [ "$fail" -eq 0 ] && [ $((pass+fail)) -eq 6 ]
