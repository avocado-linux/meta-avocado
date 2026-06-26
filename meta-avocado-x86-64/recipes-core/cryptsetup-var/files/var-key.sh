#!/bin/sh
# /var LUKS key provider for avocado-x86-64 (Intel) -- phase-1: hw-id derived
# (DMI), no provisioned secret. Phase-2 re-enrolls to the TPM2-sealed path
# (PCR 7, discrete TPM) on first boot via cryptsetup-var.sh.
#
# Emits exactly 64 raw bytes on stdout. Exit non-zero on any failure.
set -eu

# DMI identifiers are populated by the kernel early and are readable in the
# initramfs. product_uuid is per-board unique; fall back to product_serial.
HW_ID=""
for f in /sys/class/dmi/id/product_uuid /sys/class/dmi/id/product_serial; do
    if [ -r "$f" ]; then
        HW_ID=$(tr -d '\0\n' < "$f")
        [ -n "$HW_ID" ] && break
    fi
done
[ -n "$HW_ID" ] || HW_ID="intel-no-dmi-id"

SALT=$(printf '%s' "$HW_ID" | openssl dgst -sha256 -binary | head -c 16 | xxd -p -c 256)

openssl kdf \
    -keylen 64 \
    -kdfopt pass:"$HW_ID" \
    -kdfopt salt:"$SALT" \
    -kdfopt iter:3 \
    -kdfopt memcost:65536 \
    -kdfopt lanes:1 \
    ARGON2ID 2>/dev/null | xxd -r -p
