#!/bin/sh
# /var LUKS key provider for NXP i.MX8M / i.MX9 boards -- phase-1: SoC-UID
# derived, no provisioned secret.
#
# The shared provider reads a secret from /var/private/var-key-secret, which
# this machine cannot use: /var IS the LUKS volume being unlocked and is not
# mounted when this runs in the initramfs, and nothing in the tree provisions
# that file. Both qemu and avocado-x86-64 already override with a hardware-id
# provider for the same reason; this is the i.MX equivalent.
#
# Identity source: /sys/devices/soc0/serial_number - the OCOTP UID, published
# by drivers/soc/imx/soc-imx9.c (128-bit, fetched via SMC) on i.MX9 and by
# soc-imx8m.c on i.MX8M. Confirmed built in on the wrynose BSP for both
# (CONFIG_SOC_IMX9=y / CONFIG_SOC_IMX8M=y in the produced 6.18.20 .configs), so
# soc0 is registered well before the initramfs reaches the unlock.
#
# That driver is newer than some vendor kernels - it does not exist upstream in
# v6.6 at all - which is what the DT fallback below is for, and why a missing
# UID is a refusal rather than a guess. On a kernel without it, publish the UID
# as the DT serial-number from u-boot instead.
#
# SECURITY NOTE, deliberate and temporary. A key derived from the SoC UID alone
# is reproducible by anyone who can read that UID from the running system - it
# is device-binding, not a secret. That is weaker than the secret+hw-id design
# the shared provider describes, and it is accepted here only because that
# design has no provisioning path today while this one has none of the
# chicken-and-egg problem. Phase-2 replaces it with ELE-backed derivation
# (SECOEXT_FIRMWARE_NAME is "none" today, so ELE is not yet wired), which binds
# the key to hardware that will not hand it back.
#
# The cryptsetup-var.sh caller depends only on stdout - 64 raw bytes.
set -eu

SOC_UID_FILE="/sys/devices/soc0/serial_number"

HW_ID=""
if [ -r "$SOC_UID_FILE" ]; then
    HW_ID=$(tr -d '\0\n' < "$SOC_UID_FILE")
fi
if [ -z "$HW_ID" ] && [ -r /sys/firmware/devicetree/base/serial-number ]; then
    # Some u-boot configurations publish the same UID into the DT. Secondary
    # only: it is set by the bootloader rather than read from the SoC, so it is
    # the less authoritative of the two.
    HW_ID=$(tr -d '\0\n' < /sys/firmware/devicetree/base/serial-number)
fi

# Fail rather than fall back to a constant. The qemu provider substitutes a
# fixed string when no serial is readable, which is right for a disposable test
# target and wrong here: on real hardware a constant would give every board in
# the fleet the same /var key, silently, with no symptom until someone noticed
# one device's disk opening on another. A missing UID means this machine cannot
# derive a device-bound key, and refusing is the only safe answer.
if [ -z "$HW_ID" ]; then
    echo "var-key: no SoC UID at $SOC_UID_FILE (is CONFIG_SOC_IMX8M / CONFIG_SOC_IMX9 enabled?)" >&2
    echo "var-key: refusing to derive a key that would not be device-unique" >&2
    exit 1
fi

# Deterministic 16-byte salt = first 32 hex chars of SHA-256(HW_ID). Public and
# per-device; a salt is not a secret, it exists to keep the KDF output unique.
SALT=$(printf '%s' "$HW_ID" | openssl dgst -sha256 | sed 's/.*= *//' | cut -c1-32)

# Emit exactly 64 raw key bytes via Argon2id. -binary writes raw bytes to
# stdout, so no hex<->binary conversion (xxd) is needed - the minimal initramfs
# does not ship it. Parameters match the other providers: m=64MiB, t=3, p=1.
openssl kdf -binary \
    -keylen 64 \
    -kdfopt pass:"$HW_ID" \
    -kdfopt salt:"$SALT" \
    -kdfopt iter:3 \
    -kdfopt memcost:65536 \
    -kdfopt lanes:1 \
    ARGON2ID
