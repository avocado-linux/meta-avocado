SUMMARY = "extlinux.conf for the STM32MP25 Discovery Kit boot partition"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

COMPATIBLE_MACHINE = "avocado-stm32mp25-dk"

SRC_URI = "file://extlinux.conf"

S = "${WORKDIR}"

inherit deploy

do_compile[noexec] = "1"

do_deploy() {
    install -D -m 0644 ${WORKDIR}/extlinux.conf ${DEPLOYDIR}/extlinux.conf
}
addtask deploy after do_compile before do_build
