inherit cargo cargo-update-recipe-crates systemd

SRCBRANCH = "main"
SRCREV = "d9733f9b51d073b1050442cedd17bba0f7c9fe95"
SRC_URI = " \
    git://git@github.com/avocado-linux/avocado-control.git;protocol=https;nobranch=1;branch=${SRCBRANCH} \
    file://00-avocado.preset \
    file://avocado-extension.service \
    file://avocado-extension-initrd.service \
    file://sshdgenkeys-after-extensions.conf \
"

require ${BPN}-crates.inc

S = "${WORKDIR}/git"

CARGO_SRC_DIR = ""

LIC_FILES_CHKSUM = " \
    file://LICENSE;md5=86d3f3a95c324c9479bd8986968f4327 \
"

SUMMARY = "Runtime control for Avocado Linux"
HOMEPAGE = "https://github.com/avocado-linux/avocado-control"
LICENSE = "Apache-2.0"

include avocadoctl-${PV}.inc
include avocadoctl.inc

SYSTEMD_SERVICE:${PN} = "avocado-extension.service"
SYSTEMD_AUTO_ENABLE = "enable"

FILES:${PN} += " \
    ${systemd_system_unitdir}/avocado-extension-initrd.service \
    ${systemd_system_unitdir}/sshdgenkeys.service.d/avocado.conf \
    ${systemd_unitdir}/initrd-preset/98-avocadoctl.preset \
"

do_install:append() {
    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${WORKDIR}/avocado-extension.service ${D}${systemd_system_unitdir}/
    install -m 0644 ${WORKDIR}/avocado-extension-initrd.service ${D}${systemd_system_unitdir}/

    # Ensure sshdgenkeys runs after extensions are merged (openssh needs /usr overlay)
    install -d ${D}${systemd_system_unitdir}/sshdgenkeys.service.d
    install -m 0644 ${WORKDIR}/sshdgenkeys-after-extensions.conf ${D}${systemd_system_unitdir}/sshdgenkeys.service.d/avocado.conf

    install -d ${D}${sysconfdir}/systemd/system-preset
    install -m 0644 ${WORKDIR}/00-avocado.preset ${D}${sysconfdir}/systemd/system-preset/00-avocado.preset

    # systemd 258+ uses initrd-preset/ instead of system-preset/ when
    # /etc/initrd-release exists (i.e. in initramfs images).  The bbclass
    # only generates system-preset/98-*.preset, so we must provide an
    # initrd-preset file ourselves for the service to be enabled in initramfs.
    install -d ${D}${systemd_unitdir}/initrd-preset
    echo "enable avocado-extension-initrd.service" \
        > ${D}${systemd_unitdir}/initrd-preset/98-avocadoctl.preset
}

BBCLASSEXTEND = "native nativesdk"
