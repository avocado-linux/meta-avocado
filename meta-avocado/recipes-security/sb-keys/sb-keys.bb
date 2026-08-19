SUMMARY = "UEFI Secure Boot key generation recipe"
DESCRIPTION = "Generates PK/KEK/db/dbx key chain for UEFI Secure Boot. \
Self-signed RSA 2048 / SHA256 certificates produced at build time. \
Private keys are never installed to the target."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

DEPENDS = "openssl-native efitools-native"

SRC_URI = "file://gen-sbkeys.sh"

# Output directory for generated keys (override per-developer to a stable path
# outside the build tree; excluded from sstate hashing via BB_BASEHASH_IGNORE_VARS
# in avocado-security.inc).
AVOCADO_SB_KEYS_DIR ?= "${WORKDIR}/sb-keys"

# Run do_install on every build so callers always have fresh cert references,
# even when the keys already exist (idempotency is enforced inside gen-sbkeys.sh).
do_install[nostamp] = "1"

do_compile() {
    install -d "${AVOCADO_SB_KEYS_DIR}"
    chmod +x "${UNPACKDIR}/gen-sbkeys.sh"
    SBKEYS_DIR="${AVOCADO_SB_KEYS_DIR}" "${UNPACKDIR}/gen-sbkeys.sh"
}

do_install() {
    install -d "${D}${datadir}/avocado/sb-keys"

    for cert in PK KEK db dbx; do
        if [ -f "${AVOCADO_SB_KEYS_DIR}/${cert}.crt" ]; then
            install -m 0644 "${AVOCADO_SB_KEYS_DIR}/${cert}.crt" \
                "${D}${datadir}/avocado/sb-keys/${cert}.crt"
        fi
        if [ -f "${AVOCADO_SB_KEYS_DIR}/${cert}.der" ]; then
            install -m 0644 "${AVOCADO_SB_KEYS_DIR}/${cert}.der" \
                "${D}${datadir}/avocado/sb-keys/${cert}.der"
        fi
        # Private .key files are intentionally NOT installed.
    done
}

inherit deploy

do_deploy() {
    install -d "${DEPLOYDIR}/sb-keys"

    for cert in PK KEK db dbx; do
        if [ -f "${AVOCADO_SB_KEYS_DIR}/${cert}.crt" ]; then
            install -m 0644 "${AVOCADO_SB_KEYS_DIR}/${cert}.crt" \
                "${DEPLOYDIR}/sb-keys/${cert}.crt"
        fi
        if [ -f "${AVOCADO_SB_KEYS_DIR}/${cert}.der" ]; then
            install -m 0644 "${AVOCADO_SB_KEYS_DIR}/${cert}.der" \
                "${DEPLOYDIR}/sb-keys/${cert}.der"
        fi
    done
}

addtask deploy after do_install before do_build

# Only public certificates and DER-encoded certs ship to the target.
# Private .key files must never appear here.
FILES:${PN} = " \
    ${datadir}/avocado/sb-keys/PK.crt \
    ${datadir}/avocado/sb-keys/PK.der \
    ${datadir}/avocado/sb-keys/KEK.crt \
    ${datadir}/avocado/sb-keys/KEK.der \
    ${datadir}/avocado/sb-keys/db.crt \
    ${datadir}/avocado/sb-keys/db.der \
    ${datadir}/avocado/sb-keys/dbx.crt \
    ${datadir}/avocado/sb-keys/dbx.der \
"
