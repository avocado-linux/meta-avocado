#!/bin/sh
# /var LUKS key provider for qemuarm64 (phase-1: hw-id derived, no provisioned secret).
#
# QEMU TCG hardware binding is nominal - the DT serial-number is a fixed QEMU
# string, not a unique device identity. This provider exists to exercise the
# full LUKS format/open/resize flow in the feed-validation harness. Phase-2
# re-enrolls to the fTPM-sealed path once secure boot lands.
#
# The cryptsetup-var.sh caller depends only on stdout - 64 raw bytes.
set -eu

if [ -r /sys/firmware/devicetree/base/serial-number ]; then
    HW_ID=$(tr -d '\0' < /sys/firmware/devicetree/base/serial-number)
else
    HW_ID=$(awk '/^Serial/ {print $3}' /proc/cpuinfo 2>/dev/null || echo "qemuarm64-no-serial")
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
