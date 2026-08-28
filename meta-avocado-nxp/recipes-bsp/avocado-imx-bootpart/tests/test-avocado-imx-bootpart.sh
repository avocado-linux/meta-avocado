#!/usr/bin/env bash
# Host test: stub mmc/dd/od and a fake disk, check the slot->partition mapping,
# the empty-partition guard, and the read-back of PARTITION_CONFIG.
set -u
here=$(cd "$(dirname "$0")" && pwd); script=$here/../files/avocado-imx-bootpart
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin" "$work/dev"
pass=0; fail=0; ok() { echo "  ok   - $1"; pass=$((pass+1)); }; bad() { echo "  FAIL - $1"; fail=$((fail+1)); }
# state: $work/cfg holds PARTITION_CONFIG hex; boot0/boot1 content files
echo 48 > "$work/cfg"
cat > "$work/bin/mmc" <<S
#!/bin/sh
echo "mmc \$*" >> "$work/log"
case "\$1" in
  extcsd) echo "Boot configuration bytes [PARTITION_CONFIG: 0x\$(cat $work/cfg)]" ;;
  bootpart) [ "\$2" = enable ] || exit 1; printf '%02x' \$(( 0x40 | (\$3 << 3) )) > "$work/cfg" ;;
esac
S
# dd reads our fake boot partition files; od is the real one.
cat > "$work/bin/dd" <<S
#!/bin/sh
for a in "\$@"; do case "\$a" in if=*) f=\${a#if=} ;; esac; done
cat "$work/\$(basename "\$f")"
S
chmod +x "$work/bin/"*
printf '\xd1\x00\x20\x41rest' > "$work/mmcblk9boot0"; : > "$work/mmcblk9boot1"
run() { PATH="$work/bin:$PATH" AVOCADO_IMX_BOOTPART_DISK=mmcblk9 AVOCADO_IMX_BOOTPART_DEVDIR="$work" sh "$script" "$@"; }
[ "$(run status)" = a ] && ok "0x48 reads as slot a" || bad "status: $(run status)"
echo 50 > "$work/cfg"; [ "$(run status)" = b ] && ok "0x50 reads as slot b" || bad "status b: $(run status)"
echo 48 > "$work/cfg"; : > "$work/log"
out=$(run b 2>&1); echo "$out" | grep -q "refusing to enable $work/mmcblk9boot1" && ok "an empty boot1 is refused for slot b" || bad "guard: $out"
[ -s "$work/log" ] && bad "guard must refuse before touching mmc: $(cat "$work/log")" || ok "the guard refuses before any mmc command"
printf '\xd1\x00\x20\x41new' > "$work/mmcblk9boot1"
out=$(run b 2>&1)
{ echo "$out" | grep -q "now boots slot b from $work/mmcblk9boot1" && grep -q "^mmc bootpart enable 2 1 $work/mmcblk9$" "$work/log" && [ "$(cat "$work/cfg")" = 50 ]; } && ok "slot b enables boot partition 2 with BOOT_ACK and verifies it" || bad "enable: $out / $(cat "$work/log")"
out=$(run b 2>&1); echo "$out" | grep -q "already enabled" && ok "enabling the current slot is a no-op" || bad "noop: $out"
out=$(run a 2>&1); { echo "$out" | grep -q "now boots slot a from $work/mmcblk9boot0" && [ "$(cat "$work/cfg")" = 48 ]; } && ok "rollback to slot a enables boot partition 1" || bad "rollback: $out"
out=$(run c 2>&1); echo "$out" | grep -q "^usage" && ok "unknown slot is a usage error" || bad "usage: $out"
# SD card: no hardware boot partitions at all -> nothing to select, exit 0, mmc untouched
rm -f "$work/mmcblk9boot0" "$work/mmcblk9boot1"; : > "$work/log"
out=$(run b 2>&1); rc=$?
{ [ $rc -eq 0 ] && echo "$out" | grep -q "no eMMC hardware boot partitions" && [ ! -s "$work/log" ]; } && ok "a medium without boot partitions is a no-op exit 0 and mmc is never run" || bad "sd: rc=$rc $out $(cat "$work/log")"
echo; echo "passed: $pass  failed: $fail"; [ "$fail" -eq 0 ]
