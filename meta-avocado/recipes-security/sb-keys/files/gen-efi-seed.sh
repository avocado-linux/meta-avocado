#!/bin/sh
# gen-efi-seed.sh - Build the U-Boot UEFI variable seed (ubootefi.var) that
# enrols PK, KEK, db and a placeholder dbx at build time, so the firmware leaves
# setup mode with no first-boot enrolment window. See the dbx note above the
# pack invocation for what that placeholder is and is not.
#
# Input:  ${SBKEYS_DIR}/{PK,KEK,db,dbx}.der  (written by gen-sbkeys.sh)
# Output: ${SBKEYS_DIR}/ubootefi.var
#
# Usage:
#   SBKEYS_DIR=/path/to/keys ./gen-efi-seed.sh
#
# WHAT GOES IN THE STORE
#
# Each variable's value is a bare EFI_SIGNATURE_LIST of type EFI_CERT_X509_GUID
# wrapping that role's DER certificate - NOT an EFI_VARIABLE_AUTHENTICATION_2
# envelope around one. The AUTH2 descriptor exists for the SetVariable() call
# path only: lib/efi_loader/efi_variable.c strips it after verifying the
# signature and stores the signature list alone. The preseed path never goes
# through SetVariable() - efi_var_restore(buf, safe=true) in
# lib/efi_loader/efi_var_file.c hands each entry's bytes straight to
# efi_var_mem_ins() as the variable's value - and efi_sigstore_parse_sigdb()
# then parses db's value as a signature list. An AUTH2-wrapped payload would be
# stored verbatim and parsed as garbage, so image authentication would reject
# every payload while SecureBoot still read 1. That is a worse failure than the
# one this change exists to fix, because it looks like a signing bug.
#
# No signing chain is applied for the same reason: nothing verifies a signature
# on the preseed path, and the pinned U-Boot's Kconfig makes PK/KEK/db/dbx
# immutable at runtime once CONFIG_EFI_VARIABLES_PRESEED is set, so there is no
# later authenticated write for a chain to anchor.
#
# REPRODUCIBILITY
#
# The per-entry timestamp comes from SOURCE_DATE_EPOCH, never the wall clock.
# A wall-clock stamp would make every rebuild produce a different ubootefi.var,
# which makes a real key rotation indistinguishable from a rebuild.
#
# Private key files (.key) are read by nothing here and must never be installed
# to the target; this script consumes only the DER certificates.

set -eu

SBKEYS_DIR="${SBKEYS_DIR:-./sb-keys}"
SEED_OUT="${SBKEYS_DIR}/ubootefi.var"

# Digests of the DERs this run packs, written beside the seed and travelling
# with it. See the manifest block at the end of this file for why a later
# consumer must not re-derive these from the key directory.
SEED_MANIFEST="${SBKEYS_DIR}/ubootefi.var.manifest"

# A SECOND, deliberately hostile variable store, used by the HITL harness to
# prove the compiled-in seed OVERRIDES an on-medium store rather than merely
# filling in for a missing one.
#
# The harness used to test this by DELETING ubootefi.var from the ESP and
# confirming PK survived. That proves fallback-when-absent and nothing more: an
# absent file cannot override anything, so the check passes on firmware with no
# precedence rule at all. The interesting claim is that a store which IS present
# and DOES carry a different PK still loses, and only a well-formed rival store
# can test it.
#
# Well-formed is the operative word. efi_var_restore() rejects a bad magic or a
# bad CRC outright with "Invalid EFI variables file", which lands the test back
# on the absent-file case wearing a disguise. So this is packed by the same
# pack.py, from a real certificate, and differs from the true seed only in whose
# key it names.
#
# It is inert on the device by construction, not by our care: the file-store
# path calls efi_var_restore(buf, safe=false), and that branch skips every
# variable whose efi_auth_var_get_type() is not EFI_AUTH_VAR_NONE - PK, KEK, db
# and dbx are all of them. See lib/efi_loader/efi_var_file.c and efi_variable.c
# in the pinned U-Boot. The store therefore cannot enrol anything on any boot;
# the harness exists to keep that true across a firmware bump, not to discover
# whether it is true today.
SEED_ADV_OUT="${SBKEYS_DIR}/ubootefi.var.adversarial"

# Deliberately not `date +%s`. Defaulting to 0 keeps the output deterministic
# even in an environment that does not export SOURCE_DATE_EPOCH.
SEED_EPOCH="${SOURCE_DATE_EPOCH:-0}"

EFI_GLOBAL_VARIABLE_GUID="8be4df61-93ca-11d2-aa0d-00e098032b8c"
EFI_IMAGE_SECURITY_DATABASE_GUID="d719b2cb-3d3a-4596-a3bc-dad00e67656f"

for tool in sbsiglist python3 openssl; do
  command -v "${tool}" >/dev/null 2>&1 || {
    echo "gen-efi-seed: ${tool} not found on PATH" >&2
    exit 1
  }
done

for role in PK KEK db dbx; do
  if [ ! -f "${SBKEYS_DIR}/${role}.der" ]; then
    echo "gen-efi-seed: ${SBKEYS_DIR}/${role}.der missing; run gen-sbkeys.sh first" >&2
    exit 1
  fi
done

# The adversarial key. Minted here rather than in gen-sbkeys.sh on purpose:
# gen-sbkeys.sh runs on EVERY machine, and a test fixture has no business in the
# key directory of a board that never builds a seed. This script is reached only
# under the boot-integrity-poc token, which is exactly the scope the fixture has.
#
# Retained once generated, like every real role, so a rebuild does not change the
# packed bytes and a genuine key rotation stays distinguishable from a rebuild.
# The retain rule is about REPRODUCIBILITY here, not about orphaning: nothing is
# ever signed with this key, so regenerating it would break nothing - which is
# also why it needs no place in the manifest below.
if [ ! -f "${SBKEYS_DIR}/ADV.crt" ]; then
  echo "gen-efi-seed: generating the adversarial test key (signs nothing, ever)"
  openssl req -newkey rsa:2048 -nodes -keyout "${SBKEYS_DIR}/ADV.key" \
    -new -x509 -sha256 -days 3650 \
    -subj "/O=Avocado OS/CN=ADVERSARIAL Test Key DO NOT TRUST" \
    -out "${SBKEYS_DIR}/ADV.crt"
fi
# Re-derived every run for the same reason gen-sbkeys.sh re-derives its own: a
# .der left disagreeing with its .crt is a split nothing downstream detects.
openssl x509 -in "${SBKEYS_DIR}/ADV.crt" \
  -out "${SBKEYS_DIR}/ADV.der" -outform DER

workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT

# SignatureOwner is informational - it identifies who contributed the entry, not
# who may use it. One value for all three keeps the seed self-describing.
for role in PK KEK db dbx ADV; do
  sbsiglist --owner "${EFI_GLOBAL_VARIABLE_GUID}" --type x509 \
    --output "${workdir}/${role}.esl" "${SBKEYS_DIR}/${role}.der"
done

cat >"${workdir}/pack.py" <<'PYEOF'
"""Pack EFI signature lists into a U-Boot variable store (format version 1).

Layout mirrors struct efi_var_file / struct efi_var_entry as documented in the
pinned U-Boot's tools/efivar.py and implemented in lib/efi_loader/efi_var_file.c.
"""

import struct
import sys
import uuid
import zlib

UBOOT_EFI_VAR_FILE_MAGIC = 0x0161566966456255

EFI_VARIABLE_NON_VOLATILE = 0x1
EFI_VARIABLE_BOOTSERVICE_ACCESS = 0x2
EFI_VARIABLE_RUNTIME_ACCESS = 0x4
EFI_VARIABLE_TIME_BASED_AUTHENTICATED_WRITE_ACCESS = 0x20

NV_BS_RT_AT = (
    EFI_VARIABLE_NON_VOLATILE
    | EFI_VARIABLE_BOOTSERVICE_ACCESS
    | EFI_VARIABLE_RUNTIME_ACCESS
    | EFI_VARIABLE_TIME_BASED_AUTHENTICATED_WRITE_ACCESS
)

VAR_FILE_FMT = "<QQLL"
VAR_ENTRY_FMT = "<LLQ16s"


def entry(name, guid, data, tsec):
    blob = name.encode("utf_16_le") + b"\x00\x00" + data
    # U-Boot walks entries at 8-byte alignment past name + data.
    blob += bytes(((len(blob) + 7) & ~7) - len(blob))
    return (
        struct.pack(VAR_ENTRY_FMT, len(data), NV_BS_RT_AT, tsec, uuid.UUID(guid).bytes_le)
        + blob
    )


def main():
    outfile, epoch = sys.argv[1], int(sys.argv[2])
    ents = bytearray()
    for spec in sys.argv[3:]:
        name, guid, path = spec.split("=", 2)
        with open(path, "rb") as f:
            ents += entry(name, guid, f.read(), epoch)

    header = struct.pack(
        VAR_FILE_FMT,
        0,
        UBOOT_EFI_VAR_FILE_MAGIC,
        len(ents) + struct.calcsize(VAR_FILE_FMT),
        zlib.crc32(ents) & 0xFFFFFFFF,
    )
    with open(outfile, "wb") as f:
        f.write(header)
        f.write(ents)


if __name__ == "__main__":
    main()
PYEOF

# db and dbx both live under EFI_IMAGE_SECURITY_DATABASE_GUID, not the global
# variable GUID. Under the wrong GUID the firmware never finds the signature
# database, and the symptom reads as "the payload is unsigned" rather than "the
# variable is misplaced".
#
# WHY dbx IS HERE, AND WHAT IT IS NOT
#
# dbx is the forbidden-signature database. CONFIG_EFI_VARIABLES_PRESEED makes
# PK/KEK/db/dbx immutable at runtime, so a dbx that is ABSENT from the seed can
# never be populated on a fielded device - there is no authenticated write path
# left to add one. Enrolling it now is what keeps the slot open at all.
#
# What ships here is a PLACEHOLDER, deliberately: the dbx certificate that
# gen-sbkeys.sh mints alongside the others, which nothing is ever signed with.
# So it revokes nothing today. It exists so the variable is present, well
# formed, and carrying content we chose rather than absent - and so replacing it
# with a real revocation list is a change to ONE input file rather than a change
# to the store format at a point when a device is already fielded.
#
# To deploy a real one: replace ${SBKEYS_DIR}/dbx.der with the DER of the
# certificate or hash to be revoked (or extend this to pack a multi-entry ESL),
# rebuild, and reflash the bootloader. Note the reflash - that is the honest
# cost of an immutable store, and it is the reason the placeholder is worth
# shipping rather than deferring.
python3 "${workdir}/pack.py" "${SEED_OUT}" "${SEED_EPOCH}" \
  "PK=${EFI_GLOBAL_VARIABLE_GUID}=${workdir}/PK.esl" \
  "KEK=${EFI_GLOBAL_VARIABLE_GUID}=${workdir}/KEK.esl" \
  "db=${EFI_IMAGE_SECURITY_DATABASE_GUID}=${workdir}/db.esl" \
  "dbx=${EFI_IMAGE_SECURITY_DATABASE_GUID}=${workdir}/dbx.esl"

# The manifest: for each role, the SHA-256 of the DER this run actually packed.
#
# It exists because every consumer downstream was hashing the LIVE key directory
# instead, at a later task, and the two are not the same claim. The key
# directory defaults outside tmp/ and is excluded from task hashing, so it can
# be rotated in place without invalidating anything that consumed it - after
# which a fingerprint taken at u-boot's do_deploy describes a certificate the
# compiled-in seed does not carry. The board then enrols one key and is handed a
# payload signed by another, and every build-time check passes.
#
# Taken HERE, in the same run that packed the seed, from the same files the pack
# consumed. There is no window between the two for anything to change, which is
# the whole point and the reason this cannot be reconstructed later.
#
# Format: one `<role> <sha256>` line per enrolled variable. Extensible on
# purpose - dbx joined the seed after PK/KEK/db, and the next variable should
# not need a new file.
: >"${SEED_MANIFEST}"
for role in PK KEK db dbx; do
  printf '%s %s\n' "${role}" \
    "$(sha256sum "${SBKEYS_DIR}/${role}.der" | awk '{print $1}')" \
    >>"${SEED_MANIFEST}"
done

# The rival store. PK ONLY, and only PK, because PK is what the harness compares
# and a fixture should carry nothing it does not need. A store naming just one
# variable is as well-formed as one naming four - same header, same CRC over the
# entries - so the minimal form tests the precedence rule exactly as a fuller
# one would.
#
# Under the SAME name and GUID as the real PK. Substituting a DIFFERENT variable
# would test nothing: the question is whether an on-medium store can win a
# collision with the compiled-in seed, and there is no collision unless both name
# the same variable.
python3 "${workdir}/pack.py" "${SEED_ADV_OUT}" "${SEED_EPOCH}" \
  "PK=${EFI_GLOBAL_VARIABLE_GUID}=${workdir}/ADV.esl"

# Refuse to ship a rival that is accidentally the real thing. If these two ever
# compare equal, the substitution test would "pass" while proving nothing at all,
# because the store it wrote and the seed it is testing against would carry the
# same key. Cheap to check, and the failure it guards is invisible from the
# harness end.
if cmp -s "${SEED_OUT}" "${SEED_ADV_OUT}"; then
  echo "gen-efi-seed: the adversarial store is byte-identical to the real seed; the substitution test would prove nothing" >&2
  exit 1
fi

echo "gen-efi-seed: wrote ${SEED_OUT} (PK, KEK, db enrolled; dbx placeholder)"
echo "gen-efi-seed: wrote ${SEED_MANIFEST} (per-role DER digests as packed)"
echo "gen-efi-seed: wrote ${SEED_ADV_OUT} (rival PK, for the HITL precedence test)"
