#!/bin/sh
# Derive the /var LUKS key using Argon2id KDF (phase-1: software-derived).
#
# The key is bound to a hardware-unique identifier. A secret at
# /var/private/var-key-secret is mixed in when present, but nothing provisions
# it and it cannot exist on a first boot (/var is the volume being unlocked),
# so the identifier alone is the normal case - the same derivation the NXP,
# qemu and x86-64 providers use. Output is 64 raw bytes on stdout.
#
# Phase-2 replaces this with a capability-probe dispatch table:
#   /dev/tpm0 present -> systemd-cryptenroll (x86, QEMU, fTPM-enabled ARM)
#   CAAM present      -> caam-keygen black-key blob (i.MX8M Plus)
#   ELE present       -> ELE/SMW key-derive (i.MX91/93 without fTPM)
#   fallback          -> this Argon2id path (no hardware key store)
# The cryptsetup-var.sh caller depends only on stdout - 64 raw bytes.
set -eu

SECRET_FILE="/var/private/var-key-secret"

# Hardware-unique identifier, most authoritative first: the SoC UID the kernel
# reads from the chip, then the serial-number the firmware or bootloader puts
# in the device tree (the Raspberry Pi firmware does), then /proc/cpuinfo.
HW_ID=""
for f in /sys/devices/soc0/serial_number /sys/firmware/devicetree/base/serial-number; do
    if [ -z "$HW_ID" ] && [ -r "$f" ]; then
        HW_ID=$(tr -d '\0\n' < "$f")
    fi
done
if [ -z "$HW_ID" ]; then
    HW_ID=$(awk '/^Serial/ {print $3}' /proc/cpuinfo 2>/dev/null || true)
fi

# Refuse rather than fall back to a constant: a constant would give every board
# the same /var key, silently. All zeros is what some firmware reports when it
# has no serial, so it counts as missing.
case "$HW_ID" in
    ""|*[!0]*) ;;
    *) HW_ID="" ;;
esac
if [ -z "$HW_ID" ]; then
    echo "var-key: no hardware-unique identifier (SoC UID, DT serial-number or cpuinfo Serial)" >&2
    echo "var-key: refusing to derive a key that would not be device-unique" >&2
    exit 1
fi

if [ -f "$SECRET_FILE" ]; then
    PASS=$(printf '%s:%s' "$(cat "$SECRET_FILE")" "$HW_ID")
else
    PASS="$HW_ID"
fi

# Key derivation: argon2id via openssl 3.x. Salt is SHA-256(hw_id) truncated to 16 bytes - public,
# per-device, non-secret. Parameters: m=65536 (64 MiB), t=3, p=1.
SALT=$(printf '%s' "$HW_ID" | openssl dgst -sha256 | sed 's/.*= *//' | cut -c1-32)

# openssl kdf -binary emits the 64 raw key bytes directly (no hex round-trip, so
# no xxd, which the minimal initramfs does not ship). stderr is left attached so
# a KDF failure surfaces in the journal and trips set -e in the caller rather
# than yielding a silent empty key.
openssl kdf -binary \
    -keylen 64 \
    -kdfopt pass:"$PASS" \
    -kdfopt salt:"$SALT" \
    -kdfopt iter:3 \
    -kdfopt memcost:65536 \
    -kdfopt lanes:1 \
    ARGON2ID
