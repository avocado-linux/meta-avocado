#!/bin/sh
# gen-sbkeys.sh - Generate UEFI Secure Boot PK/KEK/db/dbx key chain, plus a
# separate FIT image signing key used by mkimage -k for verified boot.
#
# Idempotent PER KEY: each role is generated only if its .crt is missing, so an
# existing key is never regenerated and adding a new role to this script does
# reach a directory that already holds the older ones.
#
# It used to short-circuit on PK.crt alone, on the reasoning that PK is written
# first so its presence means the chain is complete. Two ways that was wrong.
# Adding the FIT role made every pre-existing AVOCADO_SB_KEYS_DIR permanently
# miss it - the guard saw PK.crt and exited 0 - and that directory defaults to
# ${TOPDIR}/avocado-sb-keys, which survives cleanall, TMPDIR wipes and sstate
# purges, so there was no ordinary way to notice. It also latched a partial
# keyset: `set -eu` aborts mid-script on an openssl failure or ENOSPC, but PK.crt
# is already on disk by then, so every later run reported the chain complete.
#
# The failure was silent and security-relevant rather than loud. The kernel FIT
# side does check (oe/fitimage.py, "mkimage exits with 0 also without needed
# keys"), but uboot-sign.bbclass's concat_dtb has no equivalent check: mkimage -k
# against an absent key succeeds having embedded nothing, UBOOT_FIT_CHECK_SIGN
# then passes vacuously against a blob with no /signature node, and the result is
# a bootloader built with CONFIG_FIT_SIGNATURE=y and no trust anchor - which
# accepts any FIT.
#
# Private key files (.key) are produced locally but must never be installed to
# the target (the calling recipe enforces this via FILES).
#
# Usage:
#   SBKEYS_DIR=/path/to/keys ./gen-sbkeys.sh
#
# Defaults:
#   SBKEYS_DIR=./sb-keys

set -eu

SBKEYS_DIR="${SBKEYS_DIR:-./sb-keys}"

mkdir -p "${SBKEYS_DIR}"

SUBJECT_BASE="/O=Avocado OS/CN"

# Common openssl arguments for all self-signed certs.
# RSA 2048, SHA256, 10-year validity.
DAYS=3650
BITS=2048

# gen_key <role> <subject-cn>
#
# Generates one self-signed RSA key pair plus its DER form, and does nothing at
# all when that role's .crt is already present. Never regenerate an existing
# role: a fresh PK would orphan anything already signed with the old one, and a
# fresh FIT key would make every already-flashed device reject its next kernel.
gen_key() {
  role="$1"
  cn="$2"

  if [ -f "${SBKEYS_DIR}/${role}.crt" ]; then
    echo "gen-sbkeys: ${role}.crt present, keeping it."

    # Keep the CRT, but ALWAYS re-derive the DER from it. The two are consumed
    # by different halves of the chain - the seed and its manifest carry the
    # DER, while payload signing uses the CRT and KEY - so a DER that disagrees
    # with its CRT splits the build in a way every existing check passes.
    #
    # Concretely: replace a role's .crt and .key by hand and leave the old .der
    # behind. gen-efi-seed packs the OLD certificate and records its digest;
    # db.fingerprint carries that same digest; avocado-stone compares the old
    # DER against the old digest and matches; then it signs with the NEW key and
    # sbverify passes against the NEW crt. Green build, and every device flashed
    # with the pair refuses its own kernel. The seed-manifest work does not close
    # this, because both of its inputs are the stale DER.
    #
    # Re-deriving is safe where regenerating is not: this reads the retained
    # certificate and rewrites only its encoding, so the identity is unchanged
    # and nothing already signed is orphaned. That is why the early return
    # protects the KEY and not the DER.
    openssl x509 -in "${SBKEYS_DIR}/${role}.crt" \
      -out "${SBKEYS_DIR}/${role}.der" -outform DER
    return 0
  fi

  echo "gen-sbkeys: generating ${role} (${cn})"
  openssl req -newkey "rsa:${BITS}" -nodes -keyout "${SBKEYS_DIR}/${role}.key" \
    -new -x509 -sha256 -days "${DAYS}" \
    -subj "${SUBJECT_BASE}=${cn}" \
    -out "${SBKEYS_DIR}/${role}.crt"
  openssl x509 -in "${SBKEYS_DIR}/${role}.crt" \
    -out "${SBKEYS_DIR}/${role}.der" -outform DER
}

# UEFI Secure Boot chain. The db cert generated here is the one the UEFI
# variable seed is built from, so its .crt is consumed downstream rather than
# only being an artifact of this script.
gen_key PK "Platform Key"
gen_key KEK "Key Exchange Key"
gen_key db "Signature Database"
gen_key dbx "Signature Database Exclude"

# FIT Image Signing Key - separate PKI chain used by mkimage -k to sign FIT
# images for verified boot. Deliberately NOT one of the PK/KEK/db/dbx roles
# above, because the two chains root different things: the FIT key is embedded
# in U-Boot's own control DTB and verifies a FIT payload, while db is enrolled
# in the firmware's signature database and verifies an EFI payload. One key
# serving both would give a single compromise two blast radii instead of one.
gen_key FIT "FIT Image Signing Key"

echo "gen-sbkeys: key chain complete."
echo "  Public certs (.crt/.der): safe to ship to target."
echo "  Private keys (.key):      must NOT be installed to the target."
