#!/bin/sh
# avocado-var-key-provider: usable
# Load-bearing, not a note: cryptsetup-var.bb refuses any machine whose
# resolved provider does not declare exactly one such status line. What
# this provider derives its identity from is described below.
# /var LUKS key provider for NVIDIA Jetson -- phase-1: SoC-serial derived, no
# provisioned secret. Same shape as the i.MX9 and x86 providers: this is the
# Argon2id RECOVERY keyslot (slot 0); the fTPM-sealed keyslot cryptsetup-var.sh
# enrolls on top of it is what actually binds /var to this device. A readable
# serial gives device *binding*, not secrecy - see cryptsetup-var.sh.
#
# Identity source: the /serial-number DT property, which the Jetson UEFI
# bootloader populates from the SoC's unique chip id before handing off the
# device tree, so it exists on every Orin/Thor regardless of which of the two
# feed kernels (linux-yocto or L4T linux-noble) is booted. Secondary source is
# soc0's serial_number (drivers/soc/tegra/fuse), for a boot path that does not
# populate the DT property. No identity is a refusal, never a constant: a
# constant would give every board in the fleet the same recovery key with no
# visible symptom.
set -eu

# Optional path prefix for the identity reads below, and nothing else. The
# build-time deliverability check in cryptsetup-var.bb passes a fixture root
# here; the only runtime caller, cryptsetup-var.sh, passes no arguments, so on a
# device ROOT is empty and every path resolves to the real absolute one.
ROOT="${1:-}"

# Identity sources, declared so that check knows which paths to populate. Every
# read below is prefixed with ROOT so none can fall through to the build host's
# own /sys and pass the check without the fixture having been read.
# avocado-var-key-identity: /sys/firmware/devicetree/base/serial-number
# avocado-var-key-identity: /sys/devices/soc0/serial_number
DT_SERIAL_FILE="$ROOT/sys/firmware/devicetree/base/serial-number"
SOC_UID_FILE="$ROOT/sys/devices/soc0/serial_number"

# A candidate that is blank once whitespace is discounted is NOT an identity.
# `tr -d '\0\n'` removes NULs and newlines but leaves spaces and tabs, so a DT
# serial holding only blanks passed the -z test below, was accepted as this
# board's identity, and suppressed the perfectly good soc0 source. Every board
# shipping that same blank property would then derive the same /var key. Only
# the emptiness TEST is normalised - HW_ID keeps the value exactly as read, so
# a key that derives correctly today keeps deriving the same key.
identity_is_blank() {
    # Zeros and dashes count as blank, not just whitespace. A SoC whose UID
    # fuses were never provisioned reads as 0000000000000000, which is not
    # whitespace and so was accepted as this board's identity - giving every
    # unprovisioned board of that model the same /var key, which is the exact
    # failure this provider exists to prevent. The x86-64 provider already
    # rejected the degenerate form; the rule is copied from there rather than
    # invented, so the three providers agree on what is not an identity.
    [ -z "$(printf '%s' "$1" | tr -d '0' | tr -d '-' | tr -d '[:space:]')" ]
}

HW_ID=""
if [ -r "$DT_SERIAL_FILE" ]; then
    _candidate=$(tr -d '\0\n' < "$DT_SERIAL_FILE")
    identity_is_blank "$_candidate" || HW_ID="$_candidate"
fi
if [ -z "$HW_ID" ] && [ -r "$SOC_UID_FILE" ]; then
    _candidate=$(tr -d '\0\n' < "$SOC_UID_FILE")
    identity_is_blank "$_candidate" || HW_ID="$_candidate"
fi
if [ -z "$HW_ID" ]; then
    echo "var-key: no SoC serial at $DT_SERIAL_FILE or $SOC_UID_FILE" >&2
    echo "var-key: refusing to derive a key that would not be device-unique" >&2
    exit 1
fi

# Salt is SHA-256(hw_id) truncated to 16 bytes - public, per-device, non-secret.
SALT=$(printf '%s' "$HW_ID" | openssl dgst -sha256 | sed 's/.*= *//' | cut -c1-32)

# 64 raw key bytes on stdout; stderr stays attached so a KDF failure trips
# set -e in the caller instead of yielding a silent empty key.
openssl kdf -binary \
    -keylen 64 \
    -kdfopt pass:"$HW_ID" \
    -kdfopt salt:"$SALT" \
    -kdfopt iter:3 \
    -kdfopt memcost:65536 \
    -kdfopt lanes:1 \
    ARGON2ID
