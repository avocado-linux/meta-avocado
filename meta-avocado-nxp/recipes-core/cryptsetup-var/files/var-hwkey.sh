#!/bin/sh
# /var hardware key backend for i.MX 8M: a CAAM black key.
#
# `new` asks CAAM for a random 256-bit key it will only ever hold in black
# (CAAM-encrypted) form and returns its black BLOB - the key wrapped under the
# OTPMK-derived blob key of this exact SoC. `derive` imports that blob back
# into CAAM and encrypts a fixed 64-byte block with it through AF_ALG
# (tk(cbc(aes)), NXP's tagged-key transform), so the passphrase is a function
# of a key that never exists in plaintext anywhere and that no other chip can
# unwrap. The blob is safe to store in the LUKS2 header; it is useless
# elsewhere. Both tools are NXP's (meta-freescale keyctl-caam, crypto-af-alg)
# and hard-code /data/caam as their working directory; the initramfs root is a
# writable ramfs, so that path is created on demand and scrubbed after use.
#
# Contract (see cryptsetup-var.sh): probe | name | new <blob-file> | derive <blob-file>
set -eu

CAAM_DIR=${AVOCADO_CAAM_DIR:-/data/caam}
KEY_NAME=avocado-var-kek
ZERO_IV=00000000000000000000000000000000

scrub() {
    rm -f "$CAAM_DIR/$KEY_NAME" "$CAAM_DIR/$KEY_NAME.bb" "$CAAM_DIR/black_key" 2>/dev/null || true
}

case "${1:-}" in
probe)
    [ -c /dev/caam-keygen ] || exit 1
    command -v caam-keygen >/dev/null 2>&1 || exit 1
    command -v caam-crypt >/dev/null 2>&1 || exit 1
    grep -q '^name *: *tk(cbc(aes))' "${AVOCADO_PROC_CRYPTO:-/proc/crypto}" 2>/dev/null || exit 1
    ;;
name)
    echo caam
    ;;
new)
    out=$2
    mkdir -p -m 0700 "$CAAM_DIR"
    scrub
    # CCM encapsulation carries a MAC, so a corrupted blob is refused rather
    # than silently yielding a different key.
    caam-keygen create "$KEY_NAME" ccm -s 32 >/dev/null
    [ -s "$CAAM_DIR/$KEY_NAME.bb" ] || { echo "var-hwkey: caam-keygen produced no blob" >&2; scrub; exit 1; }
    openssl base64 -A -in "$CAAM_DIR/$KEY_NAME.bb" -out "$out"
    echo >> "$out"
    scrub
    ;;
derive)
    in=$2
    mkdir -p -m 0700 "$CAAM_DIR"
    work=$(mktemp -d -p "${TMPDIR:-/run}")
    trap 'rm -rf "$work"; scrub' EXIT
    # A malformed token must be a clean refusal, not an openssl stack trace or
    # a set -e exit that skips the message.
    if ! openssl base64 -d -A -in "$in" -out "$work/blob.bb" 2>/dev/null || [ ! -s "$work/blob.bb" ]; then
        echo "var-hwkey: blob is not valid base64" >&2
        exit 1
    fi
    head -c 64 /dev/zero > "$work/zero"
    # caam-crypt imports the black key from the blob (via caam-keygen import),
    # then runs AES-256-CBC over the input with it. Its stdout is chatter.
    caam-crypt enc AES-256-CBC -k "$work/blob.bb" -in "$work/zero" -out "$work/pass" -iv "$ZERO_IV" >/dev/null 2>&1 \
        || { echo "var-hwkey: CAAM refused the blob or the transform failed" >&2; exit 1; }
    # 64 bytes plus one PKCS#7 pad block.
    [ "$(wc -c < "$work/pass")" -eq 80 ] || { echo "var-hwkey: unexpected passphrase length" >&2; exit 1; }
    cat "$work/pass"
    ;;
*)
    echo "usage: var-hwkey.sh probe|name|new <blob-file>|derive <blob-file>" >&2
    exit 2
    ;;
esac
