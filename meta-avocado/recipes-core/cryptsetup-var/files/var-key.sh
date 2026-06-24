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
SALT=$(printf '%s' "$HW_ID" | openssl dgst -sha256 -binary | head -c 16 | xxd -p -c 256)

openssl kdf \
    -keylen 64 \
    -kdfopt pass:"$(printf '%s:%s' "$SECRET" "$HW_ID")" \
    -kdfopt salt:"$SALT" \
    -kdfopt iter:3 \
    -kdfopt memcost:65536 \
    -kdfopt lanes:1 \
    ARGON2ID 2>/dev/null | xxd -r -p
