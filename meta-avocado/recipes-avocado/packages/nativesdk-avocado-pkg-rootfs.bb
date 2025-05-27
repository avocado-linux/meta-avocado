DESCRIPTION = "Avocado Rootfs Packages"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${SDK_ARCH}-${SDKPKGSUFFIX}"
PACKAGES = "${PN}"
inherit packagegroup

RDEPENDS:${PN} = "packagegroup-avocado-rootfs ${ROOTFS_IMAGE_EXTRA_INSTALL}"
