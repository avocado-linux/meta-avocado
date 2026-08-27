#!/bin/sh
# gen-efi-seed.sh - Build the U-Boot UEFI variable seed (ubootefi.var) that
# enrols PK, KEK and db at build time, so the firmware leaves setup mode with
# no first-boot enrolment window.
#
# Input:  ${SBKEYS_DIR}/{PK,KEK,db}.der  (written by gen-sbkeys.sh)
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

# Deliberately not `date +%s`. Defaulting to 0 keeps the output deterministic
# even in an environment that does not export SOURCE_DATE_EPOCH.
SEED_EPOCH="${SOURCE_DATE_EPOCH:-0}"

EFI_GLOBAL_VARIABLE_GUID="8be4df61-93ca-11d2-aa0d-00e098032b8c"
EFI_IMAGE_SECURITY_DATABASE_GUID="d719b2cb-3d3a-4596-a3bc-dad00e67656f"

for tool in sbsiglist python3; do
  command -v "${tool}" >/dev/null 2>&1 || {
    echo "gen-efi-seed: ${tool} not found on PATH" >&2
    exit 1
  }
done

for role in PK KEK db; do
  if [ ! -f "${SBKEYS_DIR}/${role}.der" ]; then
    echo "gen-efi-seed: ${SBKEYS_DIR}/${role}.der missing; run gen-sbkeys.sh first" >&2
    exit 1
  fi
done

workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT

# SignatureOwner is informational - it identifies who contributed the entry, not
# who may use it. One value for all three keeps the seed self-describing.
for role in PK KEK db; do
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

# db lives under EFI_IMAGE_SECURITY_DATABASE_GUID, not the global variable GUID.
# Under the wrong GUID the firmware never finds the signature database, and the
# symptom reads as "the payload is unsigned" rather than "the variable is
# misplaced".
python3 "${workdir}/pack.py" "${SEED_OUT}" "${SEED_EPOCH}" \
  "PK=${EFI_GLOBAL_VARIABLE_GUID}=${workdir}/PK.esl" \
  "KEK=${EFI_GLOBAL_VARIABLE_GUID}=${workdir}/KEK.esl" \
  "db=${EFI_IMAGE_SECURITY_DATABASE_GUID}=${workdir}/db.esl"

echo "gen-efi-seed: wrote ${SEED_OUT} (PK, KEK, db enrolled)"
