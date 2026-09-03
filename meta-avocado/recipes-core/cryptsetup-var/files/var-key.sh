#!/bin/sh
# Derive the /var LUKS key using Argon2id KDF (phase-1: software-derived).
#
# Reads a provisioned secret from /var/private/var-key-secret and combines
# it with a hardware-unique identifier. Output is 64 raw bytes on stdout.
#
# Phase-2 replaces this with a capability-probe dispatch table:
#   /dev/tpm0 present -> systemd-cryptenroll (x86, QEMU, fTPM-enabled ARM)
#   CAAM present      -> caam-keygen black-key blob (i.MX8M Plus)
#   ELE present       -> ELE/SMW key-derive (i.MX91/93 without fTPM)
#   fallback          -> this Argon2id path (no hardware key store)
# The cryptsetup-var.sh caller depends only on stdout - 64 raw bytes.
set -eu

# avocado-var-key-provider: unusable
# This provider requires a secret pre-provisioned at /var/private/var-key-secret,
# and nothing in this tree writes that file. Worse, /var is the volume this
# key unlocks, so a secret stored inside it is unreadable at the point the
# key is actually needed - the file cannot exist before /var does. Do not
# delete this line: it is a deliverability sentinel checked by tooling.
SECRET_FILE="/var/private/var-key-secret"
HW_ID_FILE="/sys/firmware/devicetree/base/serial-number"

if [ ! -f "$SECRET_FILE" ]; then
    echo "var-key: provisioned secret not found at $SECRET_FILE" >&2
    exit 1
fi

# Hardware-unique identifier; fall back to /proc/cpuinfo Serial if DT unavailable.
if [ -r "$HW_ID_FILE" ]; then
    HW_ID=$(tr -d '\0' < "$HW_ID_FILE")
else
    HW_ID=$(awk '/^Serial/ {print $3}' /proc/cpuinfo 2>/dev/null || echo "unknown")
fi

SECRET=$(cat "$SECRET_FILE")

# Key derivation: argon2id via openssl 3.x. Combines provisioned secret + hw-id
# as the password. Salt is SHA-256(hw_id) truncated to 16 bytes - public,
# per-device, non-secret. Parameters: m=65536 (64 MiB), t=3, p=1.
SALT=$(printf '%s' "$HW_ID" | openssl dgst -sha256 | sed 's/.*= *//' | cut -c1-32)

# openssl kdf -binary emits the 64 raw key bytes directly (no hex round-trip, so
# no xxd, which the minimal initramfs does not ship). stderr is left attached so
# a KDF failure surfaces in the journal and trips set -e in the caller rather
# than yielding a silent empty key.
openssl kdf -binary \
    -keylen 64 \
    -kdfopt pass:"$(printf '%s:%s' "$SECRET" "$HW_ID")" \
    -kdfopt salt:"$SALT" \
    -kdfopt iter:3 \
    -kdfopt memcost:65536 \
    -kdfopt lanes:1 \
    ARGON2ID
