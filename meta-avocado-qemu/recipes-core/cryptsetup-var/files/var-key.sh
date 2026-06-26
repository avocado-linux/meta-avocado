#!/bin/sh
# /var LUKS key provider for qemu (x86-64 + arm64) -- phase-1: hw-id derived,
# no provisioned secret.
#
# QEMU hardware binding is nominal - the DT serial-number (arm) / cpuinfo Serial
# (x86, usually absent) is a fixed/empty QEMU value, not a unique device
# identity. This provider exists to exercise the full LUKS format/open/resize
# flow in the feed-validation harness. Phase-2 re-enrolls to the TPM2-sealed
# path (PCR 7) on first boot via cryptsetup-var.sh (swtpm on qemu).
#
# The cryptsetup-var.sh caller depends only on stdout - 64 raw bytes.
set -eu

if [ -r /sys/firmware/devicetree/base/serial-number ]; then
    HW_ID=$(tr -d '\0' < /sys/firmware/devicetree/base/serial-number)
else
    HW_ID=$(awk '/^Serial/ {print $3}' /proc/cpuinfo 2>/dev/null || echo "qemu-no-serial")
    [ -n "$HW_ID" ] || HW_ID="qemu-no-serial"
fi

SALT=$(printf '%s' "$HW_ID" | openssl dgst -sha256 -binary | head -c 16 | xxd -p -c 256)

openssl kdf \
    -keylen 64 \
    -kdfopt pass:"$HW_ID" \
    -kdfopt salt:"$SALT" \
    -kdfopt iter:3 \
    -kdfopt memcost:65536 \
    -kdfopt lanes:1 \
    ARGON2ID 2>/dev/null | xxd -r -p
