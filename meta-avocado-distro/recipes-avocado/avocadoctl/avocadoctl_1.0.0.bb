inherit cargo cargo-update-recipe-crates systemd

SRCBRANCH = "main"
SRCREV = "59f2fcd7c0d2db79d135c3945b58d5a18bc03aa8"
SRC_URI = " \
    git://git@github.com/avocado-linux/avocado-control.git;protocol=https;nobranch=1;branch=${SRCBRANCH} \
    file://00-avocado.preset \
    file://avocado-extension.service \
"

require ${BPN}-crates.inc

S = "${WORKDIR}/git"

CARGO_SRC_DIR = ""

LIC_FILES_CHKSUM = " \
    file://LICENSE;md5=4164c7d0d31659e348a3ecfc70b41f93 \
"

SUMMARY = "Runtime control for Avocado Linux"
HOMEPAGE = "https://github.com/avocado-linux/avocado-control"
LICENSE = "Apache-2.0"

include avocadoctl-${PV}.inc
include avocadoctl.inc

SYSTEMD_SERVICE:${PN} = "avocado-extension.service"
SYSTEMD_AUTO_ENABLE = "enable"

do_install:append() {
    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${WORKDIR}/avocado-extension.service ${D}${systemd_system_unitdir}/

    install -d ${D}${sysconfdir}/systemd/system-preset
    install -m 0644 ${WORKDIR}/00-avocado.preset ${D}${sysconfdir}/systemd/system-preset/00-avocado.preset
}

BBCLASSEXTEND = "native nativesdk"
