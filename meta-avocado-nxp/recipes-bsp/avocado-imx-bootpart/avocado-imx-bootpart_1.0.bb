SUMMARY = "Select the eMMC boot partition an i.MX board boots imx-boot from"
DESCRIPTION = "Activation step for bootloader updates: avocadoctl writes the new \
imx-boot to the inactive eMMC hardware boot partition (stone slot target \
emmc-boot:<n>) and this flips PARTITION_CONFIG to it, refusing an empty partition."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://avocado-imx-bootpart"
S = "${UNPACKDIR}"

RDEPENDS:${PN} = "mmc-utils"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${UNPACKDIR}/avocado-imx-bootpart ${D}${bindir}/
}

# i.MX 8M only for now: the image guard checks the HABv4 IVT (0xD1 .. 0x41)
# that heads 8M boot images. i.MX 9 boots AHAB containers with a different
# header, so enabling would refuse every image there until the guard learns it.
COMPATIBLE_MACHINE = "(mx8m-generic-bsp)"
