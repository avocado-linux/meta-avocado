SUMMARY = "extlinux.conf for the SolidRun RZ/V2N SoM boot partition"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

COMPATIBLE_MACHINE = "avocado-rzv2n-sr-som"

SRC_URI = "file://extlinux.conf"

S = "${WORKDIR}"

inherit deploy

do_compile[noexec] = "1"

do_deploy() {
    install -D -m 0644 ${WORKDIR}/extlinux.conf ${DEPLOYDIR}/extlinux.conf
}
addtask deploy after do_compile before do_build
