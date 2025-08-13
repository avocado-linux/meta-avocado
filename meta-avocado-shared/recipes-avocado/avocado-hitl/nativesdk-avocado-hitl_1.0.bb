DESCRIPTION = "Avocado Hardware in the Loop (HITL) tools"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

PACKAGE_ARCH = "${SDKPKGARCH}"
PACKAGES = "${PN}"

SRC_URI = " \
    file://hitl-nfs.conf \
    file://avocado-hitl-server \
"

RDEPENDS:${PN} += " \
  nativesdk-ganesha \
"

inherit nativesdk

do_install() {
    install -d ${D}${bindir}
    install -d ${D}${sysconfdir}/avocado

    install -m 0755 ${WORKDIR}/avocado-hitl-server ${D}${bindir}/avocado-hitl-server
    install -m 0644 ${WORKDIR}/hitl-nfs.conf ${D}${sysconfdir}/avocado/hitl-nfs.conf
}

FILES:${PN} += " \
    ${sysconfdir}/avocado/hitl-nfs.conf \
    ${bindir}/avocado-hitl-server \
"
