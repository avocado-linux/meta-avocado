DESCRIPTION = "Avocado Hardware in the Loop (HITL) tools"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

PACKAGE_ARCH = "${SDKPKGARCH}"
PACKAGES = "${PN}"

SRC_URI = " \
    file://hitl-nfs.conf \
    file://avocado-hitl-server \
"

# Only file:// fetches — wrynose no longer auto-creates ${S}, so set
# it explicitly to UNPACKDIR (where bitbake places file:// files).
S = "${UNPACKDIR}"

RDEPENDS:${PN} += " \
  nativesdk-ganesha \
"

inherit nativesdk

do_install() {
    install -d ${D}${bindir}
    install -d ${D}${sysconfdir}/avocado

    install -m 0755 ${UNPACKDIR}/avocado-hitl-server ${D}${bindir}/avocado-hitl-server
    install -m 0644 ${UNPACKDIR}/hitl-nfs.conf ${D}${sysconfdir}/avocado/hitl-nfs.conf
}

FILES:${PN} += " \
    ${sysconfdir}/avocado/hitl-nfs.conf \
    ${bindir}/avocado-hitl-server \
"
