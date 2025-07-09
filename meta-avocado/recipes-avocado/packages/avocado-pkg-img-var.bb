DESCRIPTION = "Avocado Rootfs Image Package"
LICENSE = "Apache-2.0"

AVOCADO_PKG_IMG_RECIPE = "avocado-image-var"
AVOCADO_PKG_IMG_NAME = "${AVOCADO_PKG_IMG_RECIPE}-${MACHINE}.${AVOCADO_IMAGE_VAR_TYPE}"
AVOCADO_PKG_IMG_DEPTASK = "do_deploy"

inherit package-image
