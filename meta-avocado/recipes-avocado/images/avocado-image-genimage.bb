DESCRIPTION = "Avocado image genimage"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

inherit genimage

DEPENDS += "dosfstools-native mtools-native"

FILESEXTRAPATHS:prepend := "${@':'.join(['%s/genimage' % layer for layer in d.getVar('BBLAYERS').split()])}:"

SRC_URI:append = "${@bb.utils.contains('MACHINE_FEATURES', 'genimage', ' file://${MACHINE_SHORT_NAME}.cfg', '', d)}"

GENIMAGE_CONFIG = "${MACHINE_SHORT_NAME}.cfg"
GENIMAGE_VARIABLES[VAR-IMG] ?= "avocado-image-var-${MACHINE}.btrfs"

do_genimage[depends] += "virtual/kernel:do_deploy"
do_genimage[depends] += "${@bb.utils.contains('EFI_PROVIDER', '', '', '${EFI_PROVIDER}:do_deploy', d)}"
do_genimage[depends] += "${@' '.join(['%s:do_deploy' % dep for dep in (d.getVar('GENIMAGE_DEPENDS') or '').split()])}"
do_genimage[depends] += "avocado-image-initramfs:do_image_complete"
do_genimage[depends] += "avocado-image-rootfs:do_image_complete"
do_genimage[depends] += "avocado-image-var:do_deploy"

do_deploy:append() {
    install -m 0644 ${WORKDIR}/${MACHINE_SHORT_NAME}.cfg ${DEPLOYDIR}/genimage.cfg
}
