#!/bin/sh
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

# The device identity is the hardware serial of the disk that holds /var
# (eMMC CID, NVMe or SCSI serial: programmed by the part's maker, unique per
# chip) plus the DMI product UUID when it is not a placeholder. DMI alone is
# not enough: AMI firmware on many SBCs (LattePanda 3 Delta among them) ships
# the same product_uuid 03000200-0400-0500-0006-000700080009 on every unit,
# and product_serial is often a model code, so a DMI-only key would be shared
# by the whole fleet. $1 is the var partition (cryptsetup-var.sh passes it).
disk_id() {
  _part=$(readlink -f "${1:-}" 2>/dev/null) || return 0
  _disk=$(readlink -f "/sys/class/block/${_part##*/}/.." 2>/dev/null) || return 0
  for _f in device/cid device/serial device/wwid wwid; do
    if [ -r "$_disk/$_f" ]; then
      tr -d '\0\n ' <"$_disk/$_f"
      return 0
    fi
  done
}
DISK_ID=$(disk_id "${1:-}")

# Whitebox/OEM boards commonly ship these exact placeholder strings in DMI
# rather than leaving the field empty, so "non-empty" alone does not mean
# "unique".
DMI_ID=""
if [ -r /sys/class/dmi/id/product_uuid ]; then
  DMI_ID=$(tr -d '\0\n' </sys/class/dmi/id/product_uuid)
fi
case "$DMI_ID" in
  "Default string" | "To Be Filled By O.E.M." | "System Serial Number" | \
    "Not Specified" | "None" | "N/A" | "0123456789" | "00000000-0000-0000-0000-000000000000" | \
    "0000000000" | "03000200-0400-0500-0006-000700080009" | "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF")
    DMI_ID=""
    ;;
esac

if [ -z "$DISK_ID" ] && [ -z "$DMI_ID" ]; then
  echo "var-key: no device-unique identifier: no serial for the disk holding" >&2
  echo "var-key: /var (${1:-<not given>}) and no usable DMI product_uuid" >&2
  echo "var-key: refusing to derive a key that would not be device-unique" >&2
  exit 1
fi
HW_ID="${DISK_ID}${DMI_ID:+:$DMI_ID}"

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
