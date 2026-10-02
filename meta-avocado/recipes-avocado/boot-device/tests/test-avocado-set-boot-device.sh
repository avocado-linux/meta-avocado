#!/usr/bin/env bash
# Host test with a stubbed efibootmgr and a fake /dev + /sys tree.
#
# The case that prompted it is an AMI UEFI (SolidRun R8000): the only disk entry
# the firmware makes is "UEFI OS" with a short-form device path,
# HD(1,GPT,<guid>,...)/File(\EFI\BOOT\BOOTX64.EFI), carrying no USB(/NVMe(/SD(
# node and no class word in its description. The partition GUID is still there,
# and resolving it to a disk tells the class the device path left out.
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts, so bad runs only when the check failed
set -u
here=$(cd "$(dirname "$0")" && pwd); script=$here/../files/avocado-set-boot-device
w=$(mktemp -d); trap 'rm -rf "$w"' EXIT
pass=0; fail=0; ok(){ echo "  ok   - $1"; pass=$((pass+1)); }; bad(){ echo "  FAIL - $1"; fail=$((fail+1)); }

UA=a2e0a8c1-0003-4b01-a000-000000000001
mkdir -p "$w/bin" "$w/dev/disk/by-partuuid" "$w/sys" "$w/efivars"
# sda: a USB SSD on an xHCI controller. nvme0n1: an NVMe with no ESP.
# mmcblk0: an SD card. mmcblk1: eMMC.
mkdev() { # name, sysfs parent path, partition GUID
  d="$w/devices/$2/block/$1"; mkdir -p "$d/${1}1"
  ln -s "../devices/$2/block/$1" "$w/sys/$1"; ln -s "../devices/$2/block/$1/${1}1" "$w/sys/${1}1"
  : > "$w/dev/$1"; : > "$w/dev/${1}1"; ln -s "../../${1}1" "$w/dev/disk/by-partuuid/$3"
}
mkdev sda pci0000:00/0000:00:08.1/0000:03:00.3/usb2/2-2/2-2:1.0/host0/target0:0:0/0:0:0:0 "$UA"
mkdev nvme0n1 pci0000:00/0000:00:02.4/0000:01:00.0/nvme/nvme0 11111111-0000-0000-0000-000000000001
mkdev mmcblk0 pci0000:00/0000:00:1c.0/mmc_host/mmc0/mmc0:aaaa 22222222-0000-0000-0000-000000000001
mkdev mmcblk1 pci0000:00/0000:00:1d.0/mmc_host/mmc1/mmc1:0001 33333333-0000-0000-0000-000000000001
echo SD > "$w/devices/pci0000:00/0000:00:1c.0/mmc_host/mmc0/mmc0:aaaa/block/mmcblk0/../../type" 2>/dev/null \
  || { mkdir -p "$w/devices/pci0000:00/0000:00:1c.0/mmc_host/mmc0/mmc0:aaaa"; echo SD > "$w/devices/pci0000:00/0000:00:1c.0/mmc_host/mmc0/mmc0:aaaa/type"; }
echo MMC > "$w/devices/pci0000:00/0000:00:1d.0/mmc_host/mmc1/mmc1:0001/type"
for b in mmcblk0 mmcblk1; do ln -s ../.. "$w/sys/$b/device" 2>/dev/null || ln -s ../.. "$(readlink -f "$w/sys/$b")/device"; done

# efibootmgr stub: prints $w/entries; -o writes $w/order; -n writes $w/next.
cat > "$w/bin/efibootmgr" <<S
#!/bin/sh
case "\$1" in
  -o) echo "\$2" > "$w/order"; exit 0 ;;
  -n) echo "\$2" > "$w/next"; exit 0 ;;
esac
echo "BootCurrent: 0003"; [ -s "$w/next" ] && echo "BootNext: \$(cat "$w/next")"
echo "BootOrder: \$(cat "$w/order")"
if [ "\${1:-}" = -v ]; then cat "$w/entries"; else sed 's/\t.*//' "$w/entries"; fi
S
chmod +x "$w/bin/efibootmgr"

r8000() {
  printf 'Boot0002* UEFI: PXE IPv4 Intel(R) Ethernet Controller I226-IT\tPciRoot(0x0)/Pci(0x2,0x1)/Pci(0x0,0x0)/MAC(d063b407746c,0)/IPv4(0.0.0.0)\n' > "$w/entries"
  printf 'Boot0003* UEFI OS\tHD(1,GPT,%s,0x800,0x80000)/File(\\EFI\\BOOT\\BOOTX64.EFI)\n' "${UA^^}" >> "$w/entries"
  echo 0002,0003 > "$w/order"; : > "$w/next"
}
run(){ PATH="$w/bin:$PATH" AVOCADO_BOOT_DEVICE_EFIVARS="$w/efivars" AVOCADO_BOOT_DEVICE_DEVDIR="$w/dev" AVOCADO_BOOT_DEVICE_SYSBLOCK="$w/sys" sh "$script" "$@" 2>&1; }

# 1. The R8000's short-form entry answers to the class of the disk it names.
r8000; out=$(run --dry-run usb); rc=$?
{ [ $rc -eq 0 ] && echo "$out" | grep -q "entry 0003" && echo "$out" | grep -q "after:  0003,0002"; } \
  && ok "short-form HD() on a USB disk is recognised as usb" || bad "usb via HD guid: rc=$rc $out"

# 2. ...and not to a class it does not have: the NVMe carries no ESP entry.
out=$(run --dry-run nvme); rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q "no UEFI boot entry refers to a nvme device"; } \
  && ok "the same entry is not taken as nvme" || bad "nvme must not match: rc=$rc $out"

# 3. --once on the resolved entry writes BootNext, not BootOrder.
out=$(run --once usb); rc=$?
{ [ $rc -eq 0 ] && [ "$(cat "$w/next")" = 0003 ] && [ "$(cat "$w/order")" = 0002,0003 ]; } \
  && ok "--once writes BootNext=0003 and leaves BootOrder alone" || bad "once: rc=$rc $out next=$(cat "$w/next")"

# 4. SD and eMMC short-form entries are told apart by the MMC card type.
printf 'Boot0001* UEFI OS\tHD(1,GPT,22222222-0000-0000-0000-000000000001,0x800,0x80000)/File(\\EFI\\BOOT\\BOOTAA64.EFI)\nBoot0004* UEFI OS\tHD(1,GPT,33333333-0000-0000-0000-000000000001,0x800,0x80000)/File(\\EFI\\BOOT\\BOOTAA64.EFI)\n' > "$w/entries"
echo 0004,0001 > "$w/order"
s=$(run --dry-run sd); e=$(run --dry-run emmc)
{ echo "$s" | grep -q "entry 0001" && echo "$e" | grep -q "entry 0004"; } \
  && ok "SD and eMMC are separated by the card type" || bad "mmc classes: sd=[$s] emmc=[$e]"

# 5. Regression: a typed NVMe( node still wins, as on the Orin Nano.
printf 'Boot0001* UEFI Samsung SSD 960 EVO 250GB S3ESNX0JA13241W 1\tPcieRoot(0x40000)/Pci(0x0,0x0)/Pci(0x0,0x0)/NVMe(0x1,00-25-38-5B-71-B0-51-9A)\nBoot0002* UEFI SD Device\tVenHw(…)/SD(0x0)\n' > "$w/entries"
echo 0002,0001 > "$w/order"
out=$(run --dry-run nvme)
echo "$out" | grep -q "entry 0001" && ok "a typed NVMe( node still matches" || bad "nvme node: $out"

# 6. An HD() GUID with no partition on this system matches nothing by disk.
printf 'Boot0005* UEFI OS\tHD(1,GPT,99999999-0000-0000-0000-000000000009,0x800,0x80000)/File(\\EFI\\BOOT\\BOOTX64.EFI)\n' > "$w/entries"
echo 0005 > "$w/order"
out=$(run --dry-run usb); rc=$?
[ $rc -ne 0 ] && ok "an HD() GUID not present on this system is not guessed at" || bad "unknown guid matched: $out"

echo; echo "passed: $pass  failed: $fail  (checks: $((pass+fail))/6 run)"; [ "$fail" -eq 0 ] && [ $((pass+fail)) -eq 6 ]
