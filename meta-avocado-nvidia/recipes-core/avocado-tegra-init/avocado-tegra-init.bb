DESCRIPTION = "Detect and mount APP_<slot> partition in initramfs"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://avocado-tegra-init \
           file://avocado-tegra-init.service"

# Only file:// fetches — wrynose no longer auto-creates ${S}, so set
# it explicitly to UNPACKDIR (where bitbake places file:// files).
S = "${UNPACKDIR}"

inherit systemd

# ensure blkid, udev tools are available
DEPENDS = "util-linux udev"

# install into the initramfs image
do_install() {
    install -d ${D}${sbindir}
    install -m 0755 ${UNPACKDIR}/avocado-tegra-init ${D}${sbindir}/avocado-tegra-init

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/avocado-tegra-init.service \
        ${D}${systemd_system_unitdir}/avocado-tegra-init.service

    # systemd 258+ uses initrd-preset/ instead of system-preset/ when
    # /etc/initrd-release exists (i.e. in initramfs images).  The bbclass
    # only generates system-preset/98-*.preset, so we must provide an
    # initrd-preset file ourselves for the service to be enabled in initramfs.
    install -d ${D}${systemd_unitdir}/initrd-preset
    echo "enable avocado-tegra-init.service" \
        > ${D}${systemd_unitdir}/initrd-preset/98-avocado-tegra-init.preset
}

SYSTEMD_SERVICE:${PN} = "avocado-tegra-init.service"
SYSTEMD_AUTO_ENABLE = "enable"

FILES:${PN} += "${sbindir}/avocado-tegra-init \
                ${systemd_system_unitdir}/avocado-tegra-init.service \
                ${systemd_unitdir}/initrd-preset/98-avocado-tegra-init.preset"
