DESCRIPTION = "Avocado Initramfs Packages"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${SDK_ARCH}-${SDKPKGSUFFIX}"
PACKAGES = "${PN}"
inherit packagegroup

RDEPENDS:${PN} = "packagegroup-avocado-initramfs ${INITRAMFS_IMAGE_EXTRA_INSTALL}"
