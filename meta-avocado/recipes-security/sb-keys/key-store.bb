SUMMARY = "Package UEFI Secure Boot public certificates for target rootfs"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

# sb-keys generates the certs; this recipe packages them.
DEPENDS = "sb-keys"

# Must match the default in sb-keys.bb so the same key dir is consumed.
AVOCADO_SB_KEYS_DIR ?= "${TOPDIR}/avocado-sb-keys"

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
    done
}

# Only public certificates (.crt and .der) ship to the target.
# Private key material is intentionally absent.
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
