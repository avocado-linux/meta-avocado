SUMMARY = "LUKS2 /var unlock and first-boot-format script"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://cryptsetup-var.sh \
    file://var-key.sh \
"

RDEPENDS:${PN} = "cryptsetup"

S = "${WORKDIR}"

do_install() {
    install -d ${D}${libexecdir}/cryptsetup-var
    install -m 0750 ${WORKDIR}/cryptsetup-var.sh ${D}${libexecdir}/cryptsetup-var/
    install -m 0750 ${WORKDIR}/var-key.sh ${D}${libexecdir}/cryptsetup-var/
}

FILES:${PN} += "${libexecdir}/cryptsetup-var/"
