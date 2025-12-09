DESCRIPTION = "Avocado Initramfs Image Package"
LICENSE = "Apache-2.0"

PV = "${DISTRO_VERSION}"

AVOCADO_PKG_IMG_RECIPE = "avocado-image-initramfs"
AVOCADO_PKG_IMG_NAME = "${AVOCADO_PKG_IMG_RECIPE}-${MACHINE_SHORT_NAME}.${AVOCADO_IMAGE_INITRAMFS_TYPE}"

inherit package-image
