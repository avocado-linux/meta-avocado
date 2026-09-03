inherit cargo cargo-update-recipe-crates systemd useradd

# TEMPORARY: jschneck/bls-entry-updates, pending review and merge to main.
# Adds the `file:<partlabel>:<path>` slot target and `update.commit` actions,
# which rubikpi3's stone manifest needs to update its UKI on the ESP. Move back
# to main (and drop SRCBRANCH) once that branch lands.
SRCBRANCH = "jschneck/bls-entry-updates"
SRCREV = "0ca52b2ea67ec90e447d98ccae6d5c5b26b350f9"
SRC_URI = " \
    git://git@github.com/avocado-linux/avocado-control.git;protocol=https;nobranch=1;branch=${SRCBRANCH} \
    file://00-avocado.preset \
    file://avocado-extension.service \
    file://avocado-extension-initrd.service \
    file://avocado-ensure-extensions.service \
    file://sshdgenkeys-after-extensions.conf \
"

require ${BPN}-crates.inc


CARGO_SRC_DIR = ""

LIC_FILES_CHKSUM = " \
    file://LICENSE;md5=86d3f3a95c324c9479bd8986968f4327 \
"

SUMMARY = "Runtime control for Avocado Linux"
HOMEPAGE = "https://github.com/avocado-linux/avocadoctl"
LICENSE = "Apache-2.0"

RDEPENDS:${PN} += "util-linux-losetup"

include avocadoctl-${PV}.inc
include avocadoctl.inc

SYSTEMD_SERVICE:${PN} = "avocado-extension.service avocado-ensure-extensions.service avocadoctl.socket avocadoctl.service"
SYSTEMD_AUTO_ENABLE = "enable"

USERADD_PACKAGES = "${PN}"
GROUPADD_PARAM:${PN} = "--system --gid 997 avocado"
USERADD_PARAM:${PN} = "--system --uid 998 -g avocado --home-dir / --no-create-home --shell /sbin/nologin avocado"

FILES:${PN} += " \
    ${systemd_system_unitdir}/avocado-extension-initrd.service \
    ${systemd_system_unitdir}/sshdgenkeys.service.d/avocado.conf \
    ${systemd_unitdir}/initrd-preset/98-avocadoctl.preset \
    ${systemd_system_unitdir}/avocadoctl.service \
    ${systemd_system_unitdir}/avocadoctl.socket \
"

do_install:append() {
    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/avocado-extension.service ${D}${systemd_system_unitdir}/
    install -m 0644 ${UNPACKDIR}/avocado-extension-initrd.service ${D}${systemd_system_unitdir}/
    install -m 0644 ${UNPACKDIR}/avocado-ensure-extensions.service ${D}${systemd_system_unitdir}/
    install -m 0644 ${S}/systemd/avocadoctl.service ${D}${systemd_system_unitdir}/
    install -m 0644 ${S}/systemd/avocadoctl.socket ${D}${systemd_system_unitdir}/

    # Ensure sshdgenkeys runs after extensions are merged (openssh needs /usr overlay)
    install -d ${D}${systemd_system_unitdir}/sshdgenkeys.service.d
    install -m 0644 ${UNPACKDIR}/sshdgenkeys-after-extensions.conf ${D}${systemd_system_unitdir}/sshdgenkeys.service.d/avocado.conf

    install -d ${D}${sysconfdir}/systemd/system-preset
    install -m 0644 ${UNPACKDIR}/00-avocado.preset ${D}${sysconfdir}/systemd/system-preset/00-avocado.preset

    # systemd 258+ uses initrd-preset/ instead of system-preset/ when
    # /etc/initrd-release exists (i.e. in initramfs images).  The bbclass
    # only generates system-preset/98-*.preset, so we must provide an
    # initrd-preset file ourselves for the service to be enabled in initramfs.
    install -d ${D}${systemd_unitdir}/initrd-preset
    printf "enable avocadoctl.socket\nenable avocado-extension-initrd.service\n" \
        > ${D}${systemd_unitdir}/initrd-preset/98-avocadoctl.preset
}

BBCLASSEXTEND = "native nativesdk"
