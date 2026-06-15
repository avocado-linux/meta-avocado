FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}/env:"

# The UUU tag goes on the boot partition. For 8+, the boot partition image is
# imx-boot, so disable UUU-tagging here.
UUU_BOOTLOADER:mx8m-generic-bsp = ""

SRC_URI:append:class-target = " \
  file://avocado.cfg \
  file://env-mmc.cfg \
"

MKENVIMAGE_EXTRA_ARGS = "-r"

# Variscite's UBOOT_CONFIG[sd] = "imx8mp_var_dart_config,sdcard"; the defconfig
# we append our fragments to is the part before the comma.
UBOOT_DEFCONFIG = "imx8mp_var_dart_config"

do_configure:append:class-target () {
  cat ${WORKDIR}/avocado.cfg >> ${S}/configs/${UBOOT_DEFCONFIG}
  cat ${WORKDIR}/env-mmc.cfg >> ${S}/configs/${UBOOT_DEFCONFIG}
}

require recipes-bsp/u-boot/u-boot-env.inc
