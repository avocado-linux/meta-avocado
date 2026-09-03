#!/bin/sh
# avocado-var-key-provider: usable
# Load-bearing, not a note: cryptsetup-var.bb refuses any machine whose
# resolved provider does not declare exactly one such status line. What
# this provider derives its identity from is described below.
# /var LUKS key provider for avocado-x86-64 (Intel) -- phase-1: hw-id derived
# (DMI), no provisioned secret. Phase-2 re-enrolls to the TPM2-sealed path
# (PCR 7, discrete TPM) on first boot via cryptsetup-var.sh.
#
# SECURITY NOTE, deliberate and temporary. A key derived from a DMI identifier
# alone is reproducible by anyone who can read that identifier from the
# running system - it is device-binding, not a secret. Accepted here for the
# same reason the imx93 SoC-UID provider accepts it: no provisioning path
# exists yet, so this has none of the chicken-and-egg problem a provisioned
# secret would.
#
# Emits exactly 64 raw bytes on stdout. Exit non-zero on any failure.
set -eu

# Optional path prefix for the identity reads below, and nothing else. The
# build-time deliverability check in cryptsetup-var.bb passes a fixture root
# here; the only runtime caller, cryptsetup-var.sh, passes no arguments, so on a
# device ROOT is empty and every path resolves to the real absolute one.
#
# The prefix matters more here than on the other providers: an x86 build host
# has its own readable /sys/class/dmi/id, so an unprefixed read would be
# satisfied by the BUILD MACHINE's DMI and the check would pass without ever
# consulting the fixture.
ROOT="${1:-}"

# Identity sources, declared so that check knows which paths to populate.
# avocado-var-key-identity: /sys/class/dmi/id/product_uuid
# avocado-var-key-identity: /sys/class/dmi/id/product_serial
# DMI identifiers are populated by the kernel early and are readable in the
# initramfs. product_uuid is per-board unique; fall back to product_serial.
HW_ID=""
for f in "$ROOT/sys/class/dmi/id/product_uuid" "$ROOT/sys/class/dmi/id/product_serial"; do
    if [ -r "$f" ]; then
        HW_ID=$(tr -d '\0\n' < "$f")
        [ -n "$HW_ID" ] && break
    fi
done

# Whitebox/OEM boards commonly ship these exact placeholder strings in DMI
# rather than leaving the field empty, so "non-empty" alone does not mean
# "unique". Every board on the same OEM reference design would derive the
# same key, silently, with no symptom until someone noticed one device's
# disk opening on another - the fleet-wide-key failure this provider exists
# to avoid in the first place.
case "$HW_ID" in
    ""|"Default string"|"To Be Filled By O.E.M."|"System Serial Number"|\
    "Not Specified"|"None"|"N/A"|"0123456789"|"00000000-0000-0000-0000-000000000000"|\
    "0000000000")
        echo "var-key: no usable DMI identifier (product_uuid/product_serial" >&2
        echo "var-key: read a placeholder value: '${HW_ID}')" >&2
        echo "var-key: refusing to derive a key that would not be device-unique" >&2
        exit 1
        ;;
esac

# Salt: first 32 hex chars of SHA-256(hw_id). openssl CLI only (no xxd, which the
# minimal initramfs may not ship), matching the shared/qemu var-key providers.
SALT=$(printf '%s' "$HW_ID" | openssl dgst -sha256 | sed 's/.*= *//' | cut -c1-32)

# -binary emits the 64 raw key bytes straight to stdout, so no xxd hex<->binary
# conversion is needed. stderr is left attached so a KDF failure surfaces rather
# than yielding a silent empty key.
openssl kdf -binary \
    -keylen 64 \
    -kdfopt pass:"$HW_ID" \
    -kdfopt salt:"$SALT" \
    -kdfopt iter:3 \
    -kdfopt memcost:65536 \
    -kdfopt lanes:1 \
    ARGON2ID
