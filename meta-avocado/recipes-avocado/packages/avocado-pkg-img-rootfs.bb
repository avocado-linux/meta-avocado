DESCRIPTION = "Avocado Rootfs Image Package"
LICENSE = "Apache-2.0"

AVOCADO_PKG_IMG_RECIPE = "avocado-image-rootfs"
AVOCADO_PKG_IMG_NAME = "${AVOCADO_PKG_IMG_RECIPE}-${MACHINE}.${AVOCADO_IMAGE_ROOTFS_TYPE}"

inherit package-image
