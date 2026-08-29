#!/usr/bin/env bash
# Host test for the i.MX 8M CAAM /var key backend (files/var-hwkey.sh). No CAAM
# here: caam-keygen and caam-crypt are stubs that record their argv and write
# fixed bytes, so what is asserted is the contract the backend keeps with
# cryptsetup-var.sh and with NXP's tools - the blob round-trips through the
# token as one text line, derive is a pure function of the blob with a fixed
# input and IV, and every failure is a refusal rather than a wrong passphrase.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
backend="$here/../files/var-hwkey.sh"
pass=0; fail=0
ok()  { printf '  ok   - %s\n' "$1"; pass=$((pass+1)); }
bad() { printf '  FAIL - %s\n' "$1"; fail=$((fail+1)); }
command -v openssl >/dev/null 2>&1 || { echo "SKIP: host missing openssl"; exit 0; }

work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin" "$work/caam" "$work/run"
export PATH="$work/bin:$PATH" LOG="$work/log" AVOCADO_CAAM_DIR="$work/caam" AVOCADO_PROC_CRYPTO="$work/proc-crypto" TMPDIR="$work/run"
: > "$LOG"
# caam-keygen create <name> ccm -s 32 -> <dir>/<name> (black key) + <name>.bb (blob)
cat > "$work/bin/caam-keygen" <<S
#!/bin/sh
echo "caam-keygen \$*" >> "\$LOG"
[ "\$1" = create ] || exit 1
printf 'BLACKKEY' > "$work/caam/\$2"; printf 'BLOB-OF-%s' "\$2" > "$work/caam/\$2.bb"
S
# caam-crypt enc AES-256-CBC -k <blob> -in <f> -out <f> -iv <hex>: 80 bytes keyed on the blob content
cat > "$work/bin/caam-crypt" <<'S'
#!/bin/sh
echo "caam-crypt $*" >> "$LOG"
[ -s "$4" ] || exit 1
grep -q '^BLOB-OF-' "$4" || { echo "import failed"; exit 1; }
{ head -c 64 /dev/zero | tr '\0' 'P'; head -c 16 /dev/zero | tr '\0' 'Q'; } > "$8"
echo "chatter"
S
chmod +x "$work/bin/"*
printf 'name         : tk(cbc(aes))\n' > "$work/proc-crypto"

# --- probe ---
sh "$backend" probe >/dev/null 2>&1 && bad "probe passed without /dev/caam-keygen" || ok "probe refuses without the caam-keygen device"
[ "$(sh "$backend" name)" = caam ] && ok "backend name is caam" || bad "name: $(sh "$backend" name)"

# --- new ---
sh "$backend" new "$work/blob" || bad "new failed"
[ "$(wc -l < "$work/blob")" = 1 ] && ok "blob is one text line" || bad "blob lines: $(wc -l < "$work/blob")"
[ "$(openssl base64 -d -A -in "$work/blob")" = "BLOB-OF-avocado-var-kek" ] && ok "blob is the base64 of caam-keygen's black blob" || bad "blob content: $(cat "$work/blob")"
grep -q "^caam-keygen create avocado-var-kek ccm -s 32$" "$LOG" && ok "key is a random 256-bit CCM black key" || bad "unexpected caam-keygen argv: $(grep caam-keygen "$LOG")"
[ -e "$work/caam/avocado-var-kek" ] || [ -e "$work/caam/avocado-var-kek.bb" ] && bad "black key material left in the working dir" || ok "working dir scrubbed after new"

# --- derive ---
sh "$backend" derive "$work/blob" > "$work/pass" || bad "derive failed"
[ "$(wc -c < "$work/pass")" = 80 ] && ok "passphrase is 64 bytes + one PKCS#7 block" || bad "passphrase bytes: $(wc -c < "$work/pass")"
grep -qE "^caam-crypt enc AES-256-CBC -k /.*/blob.bb -in /.*/zero -out /.*/pass -iv 0{32}$" "$LOG" && ok "derive is AES-256-CBC over a fixed block with a zero IV, blob by absolute path" || bad "unexpected caam-crypt argv: $(grep caam-crypt "$LOG")"
sh "$backend" derive "$work/blob" | cmp -s - "$work/pass" && ok "derive is deterministic" || bad "derive not deterministic"

# --- refusals ---
echo "bm90LWEtYmxvYg==" > "$work/foreign"   # base64("not-a-blob"): the stub's import rejects it
sh "$backend" derive "$work/foreign" >"$work/out" 2>/dev/null && bad "a foreign blob yielded a passphrase" || ok "a blob the engine rejects yields nothing"
[ -s "$work/out" ] && bad "bytes written despite the refusal" || ok "no partial passphrase on refusal"
echo "%%%" > "$work/garbage"
sh "$backend" derive "$work/garbage" >/dev/null 2>&1 && bad "garbage decoded" || ok "non-base64 blob is refused"

echo; echo "passed: $pass  failed: $fail"; [ "$fail" -eq 0 ]
