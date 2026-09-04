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
#
# Whitebox/OEM boards commonly ship these exact placeholder strings in DMI
# rather than leaving the field empty, so "non-empty" alone does not mean
# "unique". Every board on the same OEM reference design would derive the same
# key, silently, with no symptom until someone noticed one device's disk
# opening on another - the fleet-wide-key failure this provider exists to
# avoid in the first place.
# Matched after normalising case and surrounding whitespace, not literally.
# DMI fields routinely carry pad spaces and vendors disagree on capitalisation,
# so an exact compare written for "To Be Filled By O.E.M." lets the lowercase
# "To be filled by O.E.M." and the padded "Default string " straight through.
# The list has to be right for BOTH sources now that each is validated in turn,
# so a gap in it is a fleet-wide key rather than one refused board.
is_placeholder() {
    # Runs of whitespace are collapsed as well as trimmed. Trimming alone left
    # "Default  string" - two spaces, which DMI fields really do carry - one
    # character away from the list entry and therefore accepted as a device
    # identity, so every board on that OEM reference design would have derived
    # one key. Collapsing normalises the compare only; HW_ID keeps the value
    # exactly as read, so no identity that already worked derives differently.
    _v=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' \
        | tr -s '[:space:]' ' ' \
        | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')

    case "$_v" in
        ""|"default string"|"to be filled by o.e.m."|"system serial number"|\
        "not specified"|"none"|"n/a"|"na"|"unknown"|"default"|"null"|\
        "0123456789"|"123456789"|"serial number"|"product name"|\
        "to be filled by oem"|"filled by o.e.m."|"chassis serial number")
            return 0
            ;;
    esac

    # Degenerate rather than named: values made only of zeros, dashes and
    # spaces. Catches "0", "0000000000" and the all-zero UUID in one test
    # instead of relying on the list carrying every width a vendor might ship.
    _stripped=$(printf '%s' "$_v" | tr -d '0' | tr -d '-' | tr -d '[:space:]')
    if [ -z "$_stripped" ]; then
        return 0
    fi

    return 1
}

# Each candidate is validated BEFORE the loop commits to it. Taking the first
# non-empty field and validating afterwards refused a board whose product_uuid
# carries an OEM placeholder even when its product_serial was perfectly
# unique - the placeholder is non-empty, so it won, and the usable source was
# never read. That is a needless refusal, not a wrong key, but it is a first
# boot that fails on hardware whose identity was there all along.
HW_ID=""
rejected=""
for f in "$ROOT/sys/class/dmi/id/product_uuid" "$ROOT/sys/class/dmi/id/product_serial"; do
    [ -r "$f" ] || continue
    candidate=$(tr -d '\0\n' < "$f")
    if is_placeholder "$candidate"; then
        rejected="$rejected ${f#"$ROOT"}='$candidate'"
        continue
    fi
    HW_ID="$candidate"
    break
done

if [ -z "$HW_ID" ]; then
    echo "var-key: no usable DMI identifier in product_uuid or product_serial" >&2
    if [ -n "$rejected" ]; then
        echo "var-key: read placeholder values:$rejected" >&2
    fi
    echo "var-key: refusing to derive a key that would not be device-unique" >&2
    exit 1
fi

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
