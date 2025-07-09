DESCRIPTION = "Avocado Rootfs Packages"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
PACKAGES = "${PN}"
inherit packagegroup

RDEPENDS:${PN} = "packagegroup-avocado-rootfs ${ROOTFS_IMAGE_EXTRA_INSTALL}"
