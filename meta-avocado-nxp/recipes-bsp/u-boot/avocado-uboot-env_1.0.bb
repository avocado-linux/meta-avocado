DESCRIPTION = "Generate fw_env.config at boot based on detected boot device"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://avocado-uboot-env \
           file://avocado-uboot-env.service"

# file://-only recipe: sources land in UNPACKDIR on wrynose, and the default
# S (${UNPACKDIR}/${BP}) never exists, which do_unpack warns about on every
# build. Point S at where the files actually are, as avocado-users does.
S = "${UNPACKDIR}"

inherit systemd

do_install() {
    install -d ${D}${sbindir}
    install -m 0755 ${UNPACKDIR}/avocado-uboot-env ${D}${sbindir}/avocado-uboot-env

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/avocado-uboot-env.service \
        ${D}${systemd_system_unitdir}/avocado-uboot-env.service
}

SYSTEMD_SERVICE:${PN} = "avocado-uboot-env.service"
SYSTEMD_AUTO_ENABLE = "enable"

FILES:${PN} = "${sbindir}/avocado-uboot-env \
               ${systemd_system_unitdir}/avocado-uboot-env.service"
