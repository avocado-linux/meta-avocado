#!/bin/sh
# avocado-var-key-provider: usable
# Load-bearing, not a note: cryptsetup-var.bb refuses any machine whose
# resolved provider does not declare exactly one such status line. What
# this provider derives its identity from is described below.
# /var LUKS key provider for qemu (x86-64 + arm64) -- phase-1: hw-id derived,
# no provisioned secret.
#
# QEMU hardware binding is nominal - the DT serial-number (arm) / cpuinfo Serial
# (x86, usually absent) is a fixed/empty QEMU value, not a unique device
# identity. This provider exists to exercise the full LUKS format/open/resize
# flow in the feed-validation harness. Phase-2 re-enrolls to the TPM2-sealed
# path (PCR 7) on first boot via cryptsetup-var.sh (swtpm on qemu).
#
# The cryptsetup-var.sh caller depends only on stdout - 64 raw bytes. Only the
# openssl CLI is used (no xxd): the initramfs already carries libcrypto via
# systemd, so cryptsetup-var RDEPENDS just adds openssl-bin.
set -eu

if [ -r /sys/firmware/devicetree/base/serial-number ]; then
    HW_ID=$(tr -d '\0' < /sys/firmware/devicetree/base/serial-number)
else
    HW_ID=$(awk '/^Serial/ {print $3}' /proc/cpuinfo 2>/dev/null || echo "qemu-no-serial")
    [ -n "$HW_ID" ] || HW_ID="qemu-no-serial"
fi

# Deterministic 16-byte salt = first 32 hex chars of SHA-256(HW_ID).
SALT=$(printf '%s' "$HW_ID" | openssl dgst -sha256 | sed 's/.*= *//' | cut -c1-32)

# Emit exactly 64 raw key bytes via Argon2id. -binary writes raw bytes to
# stdout, so no hex<->binary conversion (xxd) is needed.
openssl kdf -binary \
    -keylen 64 \
    -kdfopt pass:"$HW_ID" \
    -kdfopt salt:"$SALT" \
    -kdfopt iter:3 \
    -kdfopt memcost:65536 \
    -kdfopt lanes:1 \
    ARGON2ID
