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

# Every i.MX: the image guard now recognises both headers a boot image can
# carry -- the HABv4 IVT (0xD1 .. 0x41) on i.MX6/7/8M and the AHAB container
# (tag 0x87 at byte 3) on i.MX9x. On a medium with no eMMC hardware boot
# partitions the script is a no-op exit 0, and a board only exercises it if its
# stone manifest wires the activate/rollback hooks, so this is safe to build
# everywhere rather than adding a new override per SoC family.
COMPATIBLE_MACHINE = "(imx-generic-bsp)"
