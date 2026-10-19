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
  file://0002-pci-brcmstb-leave-the-BCM2712-RP1-link-to-the-firmwa.patch \
  file://nvme.cfg"

MKENVIMAGE_EXTRA_ARGS = "-r"

# meta-raspberrypi adds a fw_env.config to u-boot, which u-boot.inc deploys both
# as fw_env.config-${MACHINE}-${UBOOT_VERSION} and as the unversioned
# fw_env.config. libubootenv deploys Avocado's own fw_env.config under that
# unversioned name (meta-avocado-distro), with the raw MMC offsets this distro
# uses, and the meta-raspberrypi one points at /boot/uboot.env instead. Both
# recipes then install the same file into the shared deploy directory and the
# second one stops the build:
#
#   ERROR: Recipe u-boot is trying to install files into a shared area when those
#   files already exist.
#
# Drop the unversioned name so libubootenv owns it. The versioned copy stays.
do_deploy:append() {
    rm -f ${DEPLOYDIR}/fw_env.config
}

# do_configure:prepend:rpi() {
#   cat ${WORKDIR}/avocado.cfg >> ${S}/configs/${UBOOT_MACHINE}
#   cat ${WORKDIR}/env-mmc.cfg >> ${S}/configs/${UBOOT_MACHINE}
# }
