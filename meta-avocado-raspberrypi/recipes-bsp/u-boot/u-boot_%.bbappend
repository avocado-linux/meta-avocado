FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}/env:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/recipes-bsp/u-boot/files' % layer for layer in d.getVar('BBLAYERS').split() if 'meta-raspberrypi' in layer])}:"

SRC_URI:append = " \
  file://maxsize.cfg \
  file://avocado.cfg \
  file://env-mmc.cfg \
"

# Enable NVMe support for Raspberry Pi 5 (has PCIe)
SRC_URI:append:raspberrypi5 = " file://0001-pci-add-initial-support-for-Broadcom-BCM2712-SoC-PCI.patch \
  file://nvme.cfg"

MKENVIMAGE_EXTRA_ARGS = "-r"

# do_configure:prepend:rpi() {
#   cat ${WORKDIR}/avocado.cfg >> ${S}/configs/${UBOOT_MACHINE}
#   cat ${WORKDIR}/env-mmc.cfg >> ${S}/configs/${UBOOT_MACHINE}
# }
