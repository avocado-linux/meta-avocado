FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}/env:"

# The UUU tag goes on the boot partition. For 8+, the boot partition image
# is imx-boot, so disable UUU-tagging here
UUU_BOOTLOADER:mx8-generic-bsp = ""
UUU_BOOTLOADER:mx9-generic-bsp = ""

SRC_URI:append:class-target = " \
  file://avocado.cfg \
  file://env-mmc.cfg \
"

# AHAB is i.MX93-only here, so it rides a machine override rather than joining
# the class-target list above: the same bbappend serves avocado-imx95-frdm,
# which has none of the signing work wired up.
#
# SRC_URI is the whole wiring. oe-core's u-boot-configure.inc collects every
# .cfg in SRC_URI via find_cfgs() and merges them with merge_config.sh, so a
# fragment needs no do_configure of its own. Note that the class-target
# do_configure below is NOT what applies avocado.cfg and env-mmc.cfg -
# UBOOT_DEFCONFIG expands to the string "['sd']" rather than a defconfig name,
# so that cat has always written to a file named configs/[sd] that nothing
# reads. Those two fragments reach the build through find_cfgs like this one.
SRC_URI:append:imx93-frdm = " file://ahab.cfg"

MKENVIMAGE_EXTRA_ARGS = "-r"

UBOOT_DEFCONFIG = "${@'${UBOOT_CONFIG}'.split((',', 1)[0])}"

do_configure:append:class-target () {
  cat ${UNPACKDIR}/avocado.cfg >> ${S}/configs/${UBOOT_DEFCONFIG}
  cat ${UNPACKDIR}/env-mmc.cfg >> ${S}/configs/${UBOOT_DEFCONFIG}
}

require recipes-bsp/u-boot/u-boot-env.inc
