DESCRIPTION = "Assert BootOrder for a just-flashed medium from the initramfs, before switch-root"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://avocado-boot-order-assert \
           file://avocado-boot-order-assert.service"

inherit systemd

# avocado-set-boot-device does the efibootmgr/efivar work; this recipe only
# ships the marker-reading wrapper and its unit.
RDEPENDS:${PN} = "avocado-boot-device"

# install into the initramfs image
do_install() {
    install -d ${D}${sbindir}
    install -m 0755 ${WORKDIR}/avocado-boot-order-assert ${D}${sbindir}/avocado-boot-order-assert

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${WORKDIR}/avocado-boot-order-assert.service \
        ${D}${systemd_system_unitdir}/avocado-boot-order-assert.service

    # systemd 258+ uses initrd-preset/ instead of system-preset/ when
    # /etc/initrd-release exists (i.e. in initramfs images).  The bbclass
    # only generates system-preset/98-*.preset, so we must provide an
    # initrd-preset file ourselves for the service to be enabled in initramfs.
    install -d ${D}${systemd_unitdir}/initrd-preset
    echo "enable avocado-boot-order-assert.service" \
        > ${D}${systemd_unitdir}/initrd-preset/98-avocado-boot-order-assert.preset
}

SYSTEMD_SERVICE:${PN} = "avocado-boot-order-assert.service"
SYSTEMD_AUTO_ENABLE = "enable"

FILES:${PN} += "${sbindir}/avocado-boot-order-assert \
                ${systemd_system_unitdir}/avocado-boot-order-assert.service \
                ${systemd_unitdir}/initrd-preset/98-avocado-boot-order-assert.preset"
