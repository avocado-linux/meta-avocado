#!/usr/bin/env bash
# Host test for cryptsetup-var.sh's first-boot decision: which cryptsetup
# command it composes for (1) a flashed plaintext btrfs, (2) a blank partition,
# (3) an interrupted reencryption. No root and no real block device: every tool
# the script calls is a stub that records its argv, and a user+mount namespace
# supplies /etc/avocado-security-capabilities and a writable /run. The stubs'
# recorded command lines ARE the assertion - the flags below are the ones that
# decide whether the pre-seeded /var survives, so a regression here is silent
# in every other test until a board loses its primed content.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="$here/../files/cryptsetup-var.sh"
pass=0; fail=0
ok()  { printf '  ok   - %s\n' "$1"; pass=$((pass+1)); }
bad() { printf '  FAIL - %s\n' "$1"; fail=$((fail+1)); }
unshare -rm true 2>/dev/null || { echo "SKIP: no user namespaces"; exit 0; }
blk=""; for d in /dev/loop0 /dev/sda /dev/nvme0n1 /dev/vda; do [ -b "$d" ] && { blk="$d"; break; }; done
[ -n "$blk" ] || { echo "SKIP: no block device node to name"; exit 0; }

work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin" "$work/sd"
cp "$script" "$work/sd/cryptsetup-var.sh"
# key provider stub: 64 raw bytes
printf '#!/bin/sh\nhead -c 64 /dev/zero\n' > "$work/sd/var-key.sh"
# tool stubs: append argv to $LOG; behaviour keyed on $STATE dir files
cat > "$work/bin/cryptsetup" <<'S'
#!/bin/sh
echo "cryptsetup $*" >> "$LOG"
case "$1" in
  --help)     echo "  --progress-frequency=secs" ;;
  isLuks)     [ -e "$STATE/luks" ] ;;
  luksDump)   cat "$STATE/dump" 2>/dev/null; exit 0 ;;
  luksFormat) touch "$STATE/luks" ;;
  reencrypt)  touch "$STATE/luks"; rm -f "$STATE/dump" ;;
  luksOpen|open|resize) exit 0 ;;
esac
S
cat > "$work/bin/blkid" <<'S'
#!/bin/sh
echo "blkid $*" >> "$LOG"
case "$*" in *"$STATE_DEV"*) cat "$STATE/fstype" 2>/dev/null; [ -s "$STATE/fstype" ] ;; *) exit 0 ;; esac
S
cat > "$work/bin/blockdev" <<'S'
#!/bin/sh
case "$1" in --getsize64) echo 2147483648 ;; --getsz) echo 4194304 ;; esac
S
cat > "$work/bin/btrfs" <<'S'
#!/bin/sh
echo "btrfs $*" >> "$LOG"
case "$1" in
  inspect-internal) printf 'total_bytes\t\t%s\n' "$(cat "$STATE/fsbytes")" ;;
  filesystem)
    case "$2" in
      usage) [ -f "$STATE/alloc" ] && printf '    Device size:\t\t%s\n    Device allocated:\t\t%s\n    Used:\t\t\t%s\n' "$(cat "$STATE/fsbytes")" "$(cat "$STATE/alloc")" "$(cat "$STATE/alloc")" ;;
      resize) n="${3%M}"; case "$3" in
                -*) echo $(( $(cat "$STATE/fsbytes") - ${n#-} * 1048576 )) > "$STATE/fsbytes" ;;
                *)  if [ -f "$STATE/refuse_shrink" ]; then echo "ERROR: unable to resize: No space left on device" >&2; exit 1; fi
                    echo $(( n * 1048576 )) > "$STATE/fsbytes" ;;
              esac ;;
    esac ;;
esac
S
printf '#!/bin/sh\necho "mount $*" >> "$LOG"\n' > "$work/bin/mount"
printf '#!/bin/sh\necho "umount $*" >> "$LOG"\n' > "$work/bin/umount"
printf '#!/bin/sh\necho "0 4194304 crypt aes-xts-plain64 :64:logon:x 0 %s 32768 1 allow_discards"\n' "8:0" > "$work/bin/dmsetup"
printf '#!/bin/sh\nexit 0\n' > "$work/bin/modprobe"
printf '#!/bin/sh\nexit 0\n' > "$work/bin/systemd-cryptenroll"
chmod +x "$work/bin/"* "$work/sd/"*

run() { # run <state-dir>
  LOG="$1/log"; : > "$LOG"
  unshare -rm bash -c "
    mount -t tmpfs none /etc && echo 'encrypted-var ftpm tpm2' > /etc/avocado-security-capabilities
    mount -t tmpfs none /run
    mkdir -p /sys/module/dm_crypt 2>/dev/null || mount -t tmpfs none /sys/module && mkdir -p /sys/module/dm_crypt
    export PATH='$work/bin':\$PATH LOG='$LOG' STATE='$1' STATE_DEV='$blk'
    sh '$work/sd/cryptsetup-var.sh' '$blk'" >"$1/out" 2>&1 || { echo "script failed:"; cat "$1/out"; return 1; }
}

# --- Case 1: flashed 128 MiB btrfs -> in-place reencrypt confined to fs+32M ---
s="$work/c1"; mkdir -p "$s"; echo btrfs > "$s/fstype"; echo 134217728 > "$s/fsbytes"
run "$s" || bad "case 1 script exit"
if grep -q "^cryptsetup reencrypt --encrypt --type luks2 --cipher aes-xts-plain64 --key-size 512 --hash sha256 --reduce-device-size 32M --device-size 128M --progress-frequency 30 --key-file .* --batch-mode $blk\$" "$s/log"; then
  ok "plaintext btrfs is re-encrypted in place, confined to the filesystem (128M; the 32 MiB shift is added by cryptsetup), with progress"
else bad "unexpected reencrypt command: $(grep reencrypt "$s/log" || echo none)"; fi
grep -q "^cryptsetup luksFormat" "$s/log" && bad "luksFormat ran over a flashed filesystem" || ok "luksFormat never touches a flashed filesystem"
grep -q "^cryptsetup luksOpen --key-file" "$s/log" && ok "container opened with the recovery key afterwards" || bad "container not opened"

# --- Case 2: blank partition -> luksFormat (old path unchanged) ---
s="$work/c2"; mkdir -p "$s"; : > "$s/fstype"
run "$s" || bad "case 2 script exit"
grep -q "^cryptsetup luksFormat --type luks2" "$s/log" && ok "blank partition is luksFormat'ed" || bad "blank partition not formatted"
grep -q "^cryptsetup reencrypt" "$s/log" && bad "reencrypt ran on a blank partition" || ok "no reencrypt on a blank partition"

# --- Case 3: LUKS with an interrupted reencryption -> resume before open ---
s="$work/c3"; mkdir -p "$s"; touch "$s/luks"; printf 'Requirements:\tonline-reencrypt\n' > "$s/dump"
run "$s" || bad "case 3 script exit"
if grep -q "^cryptsetup reencrypt --resume-only" "$s/log" && [ "$(grep -n 'reencrypt --resume-only\|luksOpen' "$s/log" | head -1)" = "$(grep -n 'reencrypt --resume-only' "$s/log" | head -1)" ]; then
  ok "interrupted reencryption is resumed before the container is opened"
else bad "resume not attempted first: $(grep -n 'reencrypt\|luksOpen' "$s/log")"; fi

# --- Case 4: btrfs grown to fill the 2 GiB partition (deployed device, OTA turns
# encryption on) -> shrink it by the 32 MiB header deficit first, then reencrypt ---
s="$work/c4"; mkdir -p "$s"; echo btrfs > "$s/fstype"; echo 2147483648 > "$s/fsbytes"
run "$s" || bad "case 4 script exit"
if grep -q "^btrfs filesystem resize -32M /run/cryptsetup-var-shrink$" "$s/log"; then
  ok "grown btrfs is shrunk by exactly the 32 MiB header deficit"
else bad "no/unexpected shrink: $(grep 'btrfs filesystem' "$s/log" || echo none)"; fi
seq_ok=1
m=$(grep -n '^mount -t btrfs' "$s/log" | head -1 | cut -d: -f1); r=$(grep -n '^btrfs filesystem resize' "$s/log" | head -1 | cut -d: -f1)
u=$(grep -n '^umount' "$s/log" | head -1 | cut -d: -f1); e=$(grep -n '^cryptsetup reencrypt --encrypt' "$s/log" | head -1 | cut -d: -f1)
{ [ -n "$m" ] && [ -n "$r" ] && [ -n "$u" ] && [ -n "$e" ] && [ "$m" -lt "$r" ] && [ "$r" -lt "$u" ] && [ "$u" -lt "$e" ]; } || seq_ok=0
[ "$seq_ok" = 1 ] && ok "shrink is mount -> resize -> umount, all before the reencrypt" || bad "wrong shrink ordering: $(grep -n 'mount\|resize\|reencrypt --encrypt' "$s/log")"
grep -q "^cryptsetup reencrypt --encrypt .*--device-size 2016M " "$s/log" && ok "reencrypt then covers the shrunk fs (2016M; with the 32 MiB shift that is the whole partition)" || bad "unexpected device-size after shrink: $(grep 'reencrypt --encrypt' "$s/log")"
grep -q "MiB to convert" "$s/out" && ok "operator is told how much is being converted" || bad "no size/progress line on the console"

# --- Case 5: flashed small btrfs (case 1 shape) must NOT be shrunk ---
grep -q "^btrfs filesystem resize" "$work/c1/log" && bad "small flashed btrfs was shrunk needlessly" || ok "a filesystem with free tail is left alone"

# --- Case 6: grown 2 GiB btrfs with 300 MiB allocated -> shrink to allocated +
# 1.5 GiB of relocation room (1836M), so the reencrypt converts that, not the
# whole partition ---
s="$work/c6"; mkdir -p "$s"; echo btrfs > "$s/fstype"; echo 2147483648 > "$s/fsbytes"; echo 314572800 > "$s/alloc"
run "$s" || bad "case 6 script exit"
grep -q "^btrfs filesystem resize 1836M /run/cryptsetup-var-shrink$" "$s/log" && ok "grown btrfs with little data is shrunk to allocated + relocation room (1836M)" || bad "unexpected resize: $(grep 'btrfs filesystem resize' "$s/log" || echo none)"
grep -q "^cryptsetup reencrypt --encrypt .*--device-size 1836M " "$s/log" && ok "reencrypt is confined to the shrunk fs (1836M), not the partition" || bad "unexpected device-size: $(grep 'reencrypt --encrypt' "$s/log")"

# --- Case 7: btrfs refuses the aggressive shrink -> fall back to the 32 MiB one ---
s="$work/c7"; mkdir -p "$s"; echo btrfs > "$s/fstype"; echo 2147483648 > "$s/fsbytes"; echo 314572800 > "$s/alloc"; touch "$s/refuse_shrink"
run "$s" || bad "case 7 script exit"
{ grep -q "^btrfs filesystem resize 1836M " "$s/log" && grep -q "^btrfs filesystem resize -32M " "$s/log" && grep -q "^cryptsetup reencrypt --encrypt .*--device-size 2016M " "$s/log"; } && ok "a refused aggressive shrink falls back to the 32 MiB shrink and converts the whole fs" || bad "fallback not taken: $(grep -n 'resize\|reencrypt --encrypt' "$s/log")"

echo; echo "passed: $pass  failed: $fail"; [ "$fail" -eq 0 ]
