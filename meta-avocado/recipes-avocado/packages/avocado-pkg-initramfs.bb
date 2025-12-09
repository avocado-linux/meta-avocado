DESCRIPTION = "Avocado Initramfs Packages"
LICENSE = "Apache-2.0"

PV = "${DISTRO_VERSION}"

PACKAGE_ARCH = "${MACHINE_ARCH}"
PACKAGES = "${PN}"
inherit packagegroup

RDEPENDS:${PN} = "packagegroup-avocado-initramfs ${INITRAMFS_IMAGE_EXTRA_INSTALL}"
