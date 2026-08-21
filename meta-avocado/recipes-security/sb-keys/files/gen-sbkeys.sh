#!/bin/sh
# gen-sbkeys.sh - Generate UEFI Secure Boot PK/KEK/db/dbx key chain, plus a
# separate FIT image signing key used by mkimage -k for verified boot.
#
# Idempotent: exits 0 without regenerating if PK.crt already exists in SBKEYS_DIR.
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

# Idempotency check: if PK.crt already exists, the chain is complete.
if [ -f "${SBKEYS_DIR}/PK.crt" ]; then
	echo "gen-sbkeys: PK.crt already exists in ${SBKEYS_DIR}, skipping regeneration."
	exit 0
fi

echo "gen-sbkeys: generating UEFI Secure Boot key chain in ${SBKEYS_DIR}"

SUBJECT_BASE="/O=Avocado OS/CN"

# Common openssl arguments for all self-signed certs.
# RSA 2048, SHA256, 10-year validity.
DAYS=3650
BITS=2048

# Platform Key (PK) - top of the UEFI SB chain.
openssl req -newkey "rsa:${BITS}" -nodes -keyout "${SBKEYS_DIR}/PK.key" \
	-new -x509 -sha256 -days "${DAYS}" \
	-subj "${SUBJECT_BASE}=Platform Key" \
	-out "${SBKEYS_DIR}/PK.crt"
openssl x509 -in "${SBKEYS_DIR}/PK.crt" -out "${SBKEYS_DIR}/PK.der" -outform DER

# Key Exchange Key (KEK) - signed with the PK private key.
openssl req -newkey "rsa:${BITS}" -nodes -keyout "${SBKEYS_DIR}/KEK.key" \
	-new -x509 -sha256 -days "${DAYS}" \
	-subj "${SUBJECT_BASE}=Key Exchange Key" \
	-out "${SBKEYS_DIR}/KEK.crt"
openssl x509 -in "${SBKEYS_DIR}/KEK.crt" -out "${SBKEYS_DIR}/KEK.der" -outform DER

# Signature Database (db) - authorised signing certificates.
openssl req -newkey "rsa:${BITS}" -nodes -keyout "${SBKEYS_DIR}/db.key" \
	-new -x509 -sha256 -days "${DAYS}" \
	-subj "${SUBJECT_BASE}=Signature Database" \
	-out "${SBKEYS_DIR}/db.crt"
openssl x509 -in "${SBKEYS_DIR}/db.crt" -out "${SBKEYS_DIR}/db.der" -outform DER

# Signature Database Exclude (dbx) - revocation list, intentionally empty.
openssl req -newkey "rsa:${BITS}" -nodes -keyout "${SBKEYS_DIR}/dbx.key" \
	-new -x509 -sha256 -days "${DAYS}" \
	-subj "${SUBJECT_BASE}=Signature Database Exclude" \
	-out "${SBKEYS_DIR}/dbx.crt"
openssl x509 -in "${SBKEYS_DIR}/dbx.crt" -out "${SBKEYS_DIR}/dbx.der" -outform DER

# FIT Image Signing Key (FIT) - separate PKI chain used by mkimage -k to sign
# FIT images for verified boot. NOT part of the UEFI SB PK/KEK/db/dbx chain:
# this SoC does not do UEFI Secure Boot, so reusing one of those roles would
# conflate two unrelated PKI chains under one name.
openssl req -newkey "rsa:${BITS}" -nodes -keyout "${SBKEYS_DIR}/FIT.key" \
	-new -x509 -sha256 -days "${DAYS}" \
	-subj "${SUBJECT_BASE}=FIT Image Signing Key" \
	-out "${SBKEYS_DIR}/FIT.crt"
openssl x509 -in "${SBKEYS_DIR}/FIT.crt" -out "${SBKEYS_DIR}/FIT.der" -outform DER

echo "gen-sbkeys: key chain generated."
echo "  Public certs (.crt/.der): safe to ship to target."
echo "  Private keys (.key):      must NOT be installed to the target."
