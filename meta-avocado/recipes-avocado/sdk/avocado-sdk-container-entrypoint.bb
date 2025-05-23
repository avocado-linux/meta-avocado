SUMMARY = "Installs the Avocado SDK bootstrap script for container builds"
DESCRIPTION = "This recipe installs the avocado-sdk-bootstrap script into /usr/bin, making it executable, specifically for avocado-container builds."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://entrypoint"

S = "${WORKDIR}"

# This recipe should only be included in avocado-container builds
COMPATIBLE_MACHINE = "avocado-container"

RDEPENDS:${PN} += "bash"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${WORKDIR}/entrypoint ${D}${bindir}/
}

FILES:${PN} += "${bindir}/entrypoint"
