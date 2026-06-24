SUMMARY = "LUKS2 /var unlock and first-boot-format script"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://cryptsetup-var.sh \
    file://var-key.sh \
    file://cryptsetup-var.service \
"

RDEPENDS:${PN} = "cryptsetup"

inherit systemd

SYSTEMD_SERVICE:${PN} = "cryptsetup-var.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

S = "${WORKDIR}"

do_install() {
    install -d ${D}${libexecdir}/cryptsetup-var
    install -m 0750 ${WORKDIR}/cryptsetup-var.sh ${D}${libexecdir}/cryptsetup-var/
    install -m 0750 ${WORKDIR}/var-key.sh ${D}${libexecdir}/cryptsetup-var/

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${WORKDIR}/cryptsetup-var.service ${D}${systemd_system_unitdir}/
}

FILES:${PN} += "${libexecdir}/cryptsetup-var/"
FILES:${PN} += "${systemd_system_unitdir}/cryptsetup-var.service"
