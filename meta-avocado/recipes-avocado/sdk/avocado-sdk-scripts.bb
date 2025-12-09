SUMMARY = "Installs the Avocado SDK scripts"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

PV = "${SDK_VERSION}"

FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI = "file://avocado-env"

S = "${WORKDIR}"

COMPATIBLE_MACHINE = "avocado-container"

RDEPENDS:${PN} += "bash"

do_install() {
	install -d ${D}${bindir}
	install -m 0755 ${S}/avocado-env ${D}${bindir}
}
FILES:${PN} += "${bindir}/avocado-env"
