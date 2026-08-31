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
  luksDump)   cat "$STATE/dump" 2>/dev/null
              printf 'Keyslots:\n  0: luks2\n'
              [ -e "$STATE/token" ] && printf '  1: luks2\n'
              [ -e "$STATE/recovery" ] && printf '  2: luks2\n'
              [ -e "$STATE/tpm2_token" ] && printf '  3: luks2\n'
              if [ -e "$STATE/token" ] || [ -e "$STATE/tpm2_token" ]; then
                printf 'Tokens:\n'
                [ -e "$STATE/token" ] && printf '  0: avocado-hwkey\n\tKeyslot:    1\n'
                [ -e "$STATE/recovery" ] && printf '  1: avocado-recovery\n\tKeyslot:    2\n'
                [ -e "$STATE/tpm2_token" ] && printf '  3: systemd-tpm2\n\tKeyslot:    3\n'
                printf 'Digests:\n'
              fi
              exit 0 ;;
  luksFormat) touch "$STATE/luks" ;;
  reencrypt)  touch "$STATE/luks"; rm -f "$STATE/dump" ;;
  luksAddKey) [ -e "$STATE/refuse_addkey" ] && exit 1; exit 0 ;;
  luksKillSlot) exit 0 ;;
  token)      case "$2" in
                import) cp "$4" "$STATE/token" ;;
                export) cat "$STATE/token" ;;
              esac ;;
  open)       case "$*" in *--token-only*) [ -e "$STATE/tpm2_fail" ] && exit 1 ;; esac; exit 0 ;;
  luksOpen|resize) exit 0 ;;
  luksClose)  exit 0 ;;
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
printf '#!/bin/sh\n[ -e "$STATE/refuse_tpm2_enroll" ] && exit 1\nexit 0\n' > "$work/bin/systemd-cryptenroll"
# hardware key backend stub: probe obeys $STATE/hwkey_down; derive = the blob reversed
cat > "$work/hwkey.sh" <<'S'
#!/bin/sh
echo "var-hwkey $*" >> "$LOG"
case "$1" in
  probe)  [ ! -e "$STATE/hwkey_down" ] ;;
  name)   echo stubengine ;;
  new)    echo "YmxvYg==" > "$2" ;;
  derive) { [ -e "$STATE/hwkey_down" ] || [ -e "$STATE/hwkey_stale_blob" ]; } && exit 1
          tr -d '\n' < "$2" | rev; echo ;;
esac
S
chmod +x "$work/bin/"* "$work/sd/"* "$work/hwkey.sh"

run() { # run <state-dir>
  LOG="$1/log"; : > "$LOG"; rm -f "$1/posture"
  rm -f "$work/sd/var-hwkey.sh"; [ -e "$1/hwkey" ] && cp "$work/hwkey.sh" "$work/sd/var-hwkey.sh"
  hw=""; [ -e "$1/hardware" ] && hw="&& echo '$(cat "$1/hardware" 2>/dev/null)' > /etc/avocado/var-hardware"
  unshare -rm bash -c "
    mount -t tmpfs none /etc && echo 'encrypted-var ftpm tpm2' > /etc/avocado-security-capabilities && mkdir -p /etc/avocado $hw
    mount -t tmpfs none /run
    mkdir -p /sys/module/dm_crypt 2>/dev/null || mount -t tmpfs none /sys/module && mkdir -p /sys/module/dm_crypt
    export PATH='$work/bin':\$PATH LOG='$LOG' STATE='$1' STATE_DEV='$blk' TPM_DEV='$1/tpm0'
    sh '$work/sd/cryptsetup-var.sh' '$blk'; rc=\$?
    # /run is this namespace's own tmpfs: the posture file goes with it, so
    # copy it out before we leave or nothing can assert on it.
    cp /run/avocado-var-posture '$1/posture' 2>/dev/null || true
    exit \$rc" >"$1/out" 2>&1 || { echo "script failed:"; cat "$1/out"; return 1; }
}

# --- Case 1: flashed 128 MiB btrfs -> in-place reencrypt confined to fs+32M ---
s="$work/c1"; mkdir -p "$s"; echo btrfs > "$s/fstype"; echo 134217728 > "$s/fsbytes"
run "$s" || bad "case 1 script exit"
if grep -q "^cryptsetup reencrypt --encrypt --type luks2 --cipher aes-xts-plain64 --key-size 512 --hash sha256 --reduce-device-size 32M --device-size 128M --progress-frequency 30 --key-file .* --batch-mode $blk\$" "$s/log"; then
  ok "plaintext btrfs is re-encrypted in place, confined to the filesystem (128M; the 32 MiB shift is added by cryptsetup), with progress"
else bad "unexpected reencrypt command: $(grep reencrypt "$s/log" || echo none)"; fi
grep -q "^cryptsetup luksFormat" "$s/log" && bad "luksFormat ran over a flashed filesystem" || ok "luksFormat never touches a flashed filesystem"
grep -q "^cryptsetup luksOpen --link-vk-to-keyring @u::%user:cryptsetup:var --key-file" "$s/log" && ok "container opened with the recovery key afterwards" || bad "container not opened"

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

# --- Case 8: hardware key backend present, LUKS already set up, no token yet ->
# enroll a second keyslot from the engine and record its blob as a token ---
s="$work/c8"; mkdir -p "$s"; touch "$s/luks" "$s/hwkey"
run "$s" || bad "case 8 script exit"
grep -q "^cryptsetup luksAddKey --key-file .* --new-keyfile .* --new-key-slot 1 --pbkdf pbkdf2 --pbkdf-force-iterations 1000 --batch-mode $blk\$" "$s/log" \
  && ok "hardware keyslot is added into the first free slot with a cheap PBKDF, unlocked by the recovery key" \
  || bad "unexpected luksAddKey: $(grep luksAddKey "$s/log" || echo none)"
grep -q '"type":"avocado-hwkey","keyslots":\["1"\],"backend":"stubengine","blob":"YmxvYg=="' "$s/token" 2>/dev/null \
  && ok "token carries type, keyslot, backend name and the blob" || bad "token missing/wrong: $(cat "$s/token" 2>/dev/null)"
grep -q "^cryptsetup luksOpen --link-vk-to-keyring @u::%user:cryptsetup:var --key-file" "$s/log" && ok "first boot still opened with the recovery key" || bad "no recovery open"
grep -q "^VAR_HWKEY_TOKEN=yes$" "$s/posture" && ok "posture records the hardware keyslot token" || bad "posture VAR_HWKEY_TOKEN: $(cat "$s/posture" 2>/dev/null)"

# --- Case 9: token present and engine up -> open via the engine, never Argon2id ---
s="$work/c9"; mkdir -p "$s"; touch "$s/luks" "$s/hwkey"; cp "$work/c8/token" "$s/token"
run "$s" || bad "case 9 script exit"
grep -q "^cryptsetup token export --token-id 0 $blk\$" "$s/log" && ok "blob is read back from the header token" || bad "no token export"
grep -q "^var-hwkey derive " "$s/log" && ok "engine derives the passphrase from the blob" || bad "derive not called"
[ "$(grep -c '^cryptsetup luksOpen' "$s/log")" = 1 ] && ok "exactly one open" || bad "open count: $(grep -c '^cryptsetup luksOpen' "$s/log")"
grep -q "^cryptsetup luksAddKey" "$s/log" && bad "re-enrolled although a token exists" || ok "enroll is idempotent"
grep -q "opened via hardware key (stubengine)" "$s/out" && ok "posture: unlock method is the hardware key" || bad "hwkey open not reported: $(grep -i 'opened' "$s/out")"

# --- Case 10: token present but engine down -> recovery key, loud, no re-enroll ---
s="$work/c10"; mkdir -p "$s"; touch "$s/luks" "$s/hwkey" "$s/hwkey_down"; cp "$work/c8/token" "$s/token"
run "$s" || bad "case 10 script exit"
grep -q "^cryptsetup luksOpen --link-vk-to-keyring @u::%user:cryptsetup:var --key-file" "$s/log" && ok "falls back to the Argon2id recovery key" || bad "no recovery open"
grep -q "hardware key unavailable" "$s/out" && ok "fallback is reported" || bad "silent fallback"
grep -q "^cryptsetup luksAddKey" "$s/log" && bad "tried to enroll with the engine down" || ok "no enroll while the engine is down"

# --- Case 11: luksAddKey refused -> no token written, boot continues ---
s="$work/c11"; mkdir -p "$s"; touch "$s/luks" "$s/hwkey" "$s/refuse_addkey"
run "$s" || bad "case 11 script exit"
[ -e "$s/token" ] && bad "token imported although the keyslot was not added" || ok "no orphan token after a failed keyslot add"

# --- Case 13: recovery slot enrolled by the operator and the engine opened /var
# -> the derived (untokened) Argon2id slot 0 is retired; volume key linked ---
s="$work/c13"; mkdir -p "$s"; touch "$s/luks" "$s/hwkey" "$s/recovery"; cp "$work/c8/token" "$s/token"
run "$s" || bad "case 13 script exit"
grep -q "^cryptsetup luksKillSlot --batch-mode $blk 0$" "$s/log" && ok "derived keyslot retired once a recovery slot exists and the engine opened /var" || bad "derived slot kept: $(grep -c luksKillSlot "$s/log")"
grep -q "^cryptsetup luksOpen --link-vk-to-keyring @u::%user:cryptsetup:var --key-file" "$s/log" && ok "volume key is linked into root's user keyring on open" || bad "no --link-vk-to-keyring: $(grep luksOpen "$s/log")"
grep -q "^VAR_RECOVERY=key$" "$s/posture" && ok "posture reports the operator recovery key" || bad "posture VAR_RECOVERY: $(cat "$s/posture" 2>/dev/null)"

# --- Case 14: recovery slot present but the engine is down -> the derived slot
# is what opened /var this boot; it must NOT be retired ---
s="$work/c14"; mkdir -p "$s"; touch "$s/luks" "$s/hwkey" "$s/hwkey_down" "$s/recovery"; cp "$work/c8/token" "$s/token"
run "$s" || bad "case 14 script exit"
grep -q "^cryptsetup luksKillSlot" "$s/log" && bad "retired the slot that just opened /var" || ok "derived keyslot kept while it is the one that worked"

# --- Case 15: no recovery slot -> nothing retired ---
grep -q "^cryptsetup luksKillSlot" "$work/c9/log" && bad "retired a slot without a recovery token" || ok "no retirement without an operator recovery slot"

# --- Case 16: var.hardware=caam required but the engine is down -> refuse
# before touching the container (unit fails -> emergency), no open ---
s="$work/c16"; mkdir -p "$s"; echo btrfs > "$s/fstype"; echo 134217728 > "$s/fsbytes"; touch "$s/hwkey" "$s/hwkey_down"; echo caam > "$s/hardware"
if run "$s"; then bad "booted on the derived key although var.hardware=caam was unmet"; else ok "var.hardware=caam with the engine down refuses to fall back"; fi
grep -q "var.hardware=caam" "$s/out" && ok "refusal names the requirement" || bad "no requirement in message: $(cat "$s/out")"
grep -q "^cryptsetup" "$s/log" && bad "cryptsetup ran despite the refusal" || ok "nothing touched before the refusal"

# --- Case 17: var.hardware=caam and the engine is up -> normal enrol ---
s="$work/c17"; mkdir -p "$s"; touch "$s/luks" "$s/hwkey"; echo caam > "$s/hardware"
run "$s" || bad "case 17 script exit"
grep -q "^cryptsetup luksAddKey" "$s/log" && ok "var.hardware=caam with the engine up enrols as usual" || bad "no enrol with engine up"

# --- Case 18: var.hardware=none -> no hardware enrol even with an engine present ---
s="$work/c18"; mkdir -p "$s"; touch "$s/luks" "$s/hwkey"; echo none > "$s/hardware"
run "$s" || bad "case 18 script exit"
grep -q "^cryptsetup luksAddKey" "$s/log" && bad "enrolled a hardware slot with var.hardware=none" || ok "var.hardware=none enrols no hardware keyslot"
grep -q "^VAR_HARDWARE=none$" "$s/posture" && ok "posture reports var.hardware=none" || bad "posture VAR_HARDWARE: $(cat "$s/posture" 2>/dev/null)"

# --- Cases 19-24: what var.hardware=caam|tpm2 actually promise. The preflight
# (case 16) only proves the engine probes; these cover the two ways a boot could
# still end up on the derived key afterwards - an existing hardware token that
# will not unlock, and an enrolment that fails - and the first-enrolment open
# that must stay allowed. ---

# Case 19: caam, a hardware token exists, engine down -> must NOT open on the
# derived key. The engine is down, so the hwkey open is never attempted: any
# luksOpen in the log is the derived one.
# The engine probes fine here, so the preflight passes and this reaches the
# open - the blob just no longer derives (key store wiped, fuses changed).
s="$work/c19"; mkdir -p "$s"; touch "$s/luks" "$s/hwkey" "$s/hwkey_stale_blob"; cp "$work/c8/token" "$s/token"; echo caam > "$s/hardware"
if run "$s"; then bad "opened /var although the required caam keyslot failed"; else ok "var.hardware=caam refuses the derived fallback once a hardware token exists"; fi
grep -q "^cryptsetup luksOpen" "$s/log" && bad "opened on the derived key: $(grep luksOpen "$s/log")" || ok "no derived open when the required engine cannot unlock"

# Case 20: same state under auto -> still falls back, so the default is unchanged.
s="$work/c20"; mkdir -p "$s"; touch "$s/luks" "$s/hwkey" "$s/hwkey_stale_blob"; cp "$work/c8/token" "$s/token"
run "$s" || bad "case 20 script exit"
grep -q "^VAR_UNLOCK_METHOD=argon2id$" "$s/posture" && ok "var.hardware=auto still degrades to the derived key" || bad "auto did not fall back: $(cat "$s/posture" 2>/dev/null)"

# Case 21: caam, no token yet (first enrolment) but the keyslot add fails ->
# the boot must not be left on the derived key, and /var is closed again.
s="$work/c21"; mkdir -p "$s"; touch "$s/luks" "$s/hwkey" "$s/refuse_addkey"; echo caam > "$s/hardware"
if run "$s"; then bad "completed the boot although the caam keyslot could not be enrolled"; else ok "var.hardware=caam aborts when enrolment fails"; fi
grep -q "^cryptsetup luksClose var$" "$s/log" && ok "the derived-key mapping is torn down on a failed requirement" || bad "left /var open: $(grep -c luksClose "$s/log") luksClose"

# Case 22: same failure under auto -> warns and boots on the derived key.
s="$work/c22"; mkdir -p "$s"; touch "$s/luks" "$s/hwkey" "$s/refuse_addkey"
run "$s" || bad "case 22 script exit"
grep -q "hardware keyslot add failed" "$s/out" && ok "var.hardware=auto reports a failed enrol and carries on" || bad "no warning: $(cat "$s/out")"

# Case 23: tpm2, a TPM2 token exists and the TPM is present, but the unseal
# fails -> no derived fallback. (Case 10 covers the same shape under auto.)
s="$work/c25"; mkdir -p "$s"; touch "$s/luks" "$s/tpm0" "$s/tpm2_fail"; printf 'Tokens:\n  0: systemd-tpm2\n' > "$s/dump"; echo tpm2 > "$s/hardware"
if run "$s"; then bad "opened /var although the required TPM2 keyslot failed"; else ok "var.hardware=tpm2 refuses the derived fallback once a TPM2 token exists"; fi
grep -q "^cryptsetup luksOpen" "$s/log" && bad "opened on the derived key: $(grep luksOpen "$s/log")" || ok "no derived open when the TPM2 keyslot cannot unlock"

# Case 24: tpm2, no token yet -> the derived open IS allowed (it is the only way
# in before a keyslot exists), but a refused enrolment still fails the boot.
s="$work/c24"; mkdir -p "$s"; touch "$s/luks" "$s/tpm0" "$s/refuse_tpm2_enroll"; echo tpm2 > "$s/hardware"
if run "$s"; then bad "completed the boot although the TPM2 keyslot could not be enrolled"; else ok "var.hardware=tpm2 aborts when enrolment fails"; fi
grep -q "^cryptsetup luksOpen" "$s/log" && ok "the first-enrolment derived open is still allowed" || bad "no derived open on the first-enrolment boot"

# --- Case 20: a device enrolled under `auto` carries BOTH tokens; var.hardware=tpm2
# with a failing TPM2 unseal must NOT be satisfied by the working hardware key ---
s="$work/c20"; mkdir -p "$s"; touch "$s/luks" "$s/token" "$s/tpm2_token" "$s/hwkey" "$s/tpm2_fail"; echo tpm2 > "$s/hardware"
run "$s" && bad "case 20: mixed tokens with a failing TPM2 opened anyway" || ok "an explicit tpm2 mode is not satisfied by a working hardware keyslot"
# The blob export is how the hardware key is read to open the container, so its
# absence is proof that engine was never tried.
grep -q "^cryptsetup token export --token-id 0 " "$s/log" && bad "case 20: read the hardware key blob under var.hardware=tpm2" || ok "the hardware key is not even attempted in tpm2 mode"

# --- Case 21: the mirror image - var.hardware=caam on a device whose only
# hardware token is TPM2 must refuse rather than open on the derived key ---
s="$work/c21"; mkdir -p "$s"; touch "$s/luks" "$s/tpm2_token" "$s/hwkey"; echo caam > "$s/hardware"
run "$s" && bad "case 21: caam mode opened a TPM2-enrolled device" || ok "an explicit caam mode refuses a device enrolled only with TPM2"

# --- Case 22: `auto` still tries both, so a working hardware key opens a
# mixed-token device even when the TPM2 unseal fails ---
s="$work/c22"; mkdir -p "$s"; touch "$s/luks" "$s/token" "$s/tpm2_token" "$s/hwkey" "$s/tpm2_fail"; echo auto > "$s/hardware"
run "$s" || bad "case 22 script exit"
{ grep -q "^cryptsetup token export --token-id 0 " "$s/log" && ! grep -q -- "--token-only" "$s/log"; } \
  && ok "auto still opens with the hardware key and never reaches the failing TPM2" \
  || bad "case 22: auto did not use the hardware key"

# --- Case 25: the var partition is already mounted -> refuse, touch nothing ---
s="$work/c25"; mkdir -p "$s"; echo btrfs > "$s/fstype"; echo 134217728 > "$s/fsbytes"
printf '%s /var btrfs rw 0 0\n' "$blk" > "$s/mounts"
LOG="$s/log"; : > "$LOG"
if unshare -rm bash -c "
    mount -t tmpfs none /etc && echo 'encrypted-var' > /etc/avocado-security-capabilities
    mount -t tmpfs none /run; mkdir -p /sys/module/dm_crypt 2>/dev/null || { mount -t tmpfs none /sys/module && mkdir -p /sys/module/dm_crypt; }
    export PATH='$work/bin':\$PATH LOG='$LOG' STATE='$s' STATE_DEV='$blk' AVOCADO_PROC_MOUNTS='$s/mounts'
    sh '$work/sd/cryptsetup-var.sh' '$blk'" >"$s/out" 2>&1; then bad "script succeeded on a mounted var partition"; else ok "a mounted var partition is refused (unit fails -> emergency)"; fi
grep -q "already mounted" "$s/out" && ok "refusal names the mounted device" || bad "no refusal message: $(cat "$s/out")"
grep -q "^cryptsetup" "$s/log" && bad "cryptsetup was invoked on a mounted device" || ok "no cryptsetup call before the refusal"

echo; echo "passed: $pass  failed: $fail"; [ "$fail" -eq 0 ]
