FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}/env:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/recipes-bsp/u-boot/files' % layer for layer in d.getVar('BBLAYERS').split() if 'meta-raspberrypi' in layer])}:"

SRC_URI:append = " \
  file://maxsize.cfg \
  file://avocado.cfg \
  file://env-mmc.cfg \
"

MKENVIMAGE_EXTRA_ARGS = "-r"

# do_configure:prepend:rpi() {
#   cat ${WORKDIR}/avocado.cfg >> ${S}/configs/${UBOOT_MACHINE}
#   cat ${WORKDIR}/env-mmc.cfg >> ${S}/configs/${UBOOT_MACHINE}
# }
