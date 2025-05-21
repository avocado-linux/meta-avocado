DESCRIPTION = "Packagegroup for inclusion in Avocado initramfs image"
LICENSE = "Apache-2.0"

inherit packagegroup

RDEPENDS:${PN} = "\
  cryptsetup \
  systemd \
  systemd-extra-utils \
  os-release-initrd \
  ${INITRAMFS_IMAGE_EXTRA_INSTALL} \
"
