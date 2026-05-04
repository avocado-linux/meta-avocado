DESCRIPTION = "Avocado UFS Image Package"
LICENSE = "Apache-2.0"

PV = "${DISTRO_VERSION}"

AVOCADO_PKG_IMG_RECIPE = "avocado-image-rootfs"
AVOCADO_PKG_IMG_NAME = "${AVOCADO_PKG_IMG_RECIPE}-${MACHINE_SHORT_NAME}.ufs.tar.gz"
AVOCADO_PKG_IMG_DEPTASK = "do_deploy_fixup"

inherit package-image
