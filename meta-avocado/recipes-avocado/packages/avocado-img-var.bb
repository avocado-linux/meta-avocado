DESCRIPTION = "Avocado Var Image Package"
LICENSE = "Apache-2.0"

AVOCADO_PKG_IMG_RECIPE = "avocado-image-var"
AVOCADO_PKG_IMG_NAME = "${AVOCADO_PKG_IMG_RECIPE}-${MACHINE_SHORT_NAME}.${AVOCADO_IMAGE_VAR_TYPE}"
AVOCADO_PKG_IMG_DEPTASK = "do_deploy"

# Prevent automatic dependency detection for image packages
RDEPENDS:${PN} = ""
INHIBIT_PACKAGE_STRIP = "1"
INHIBIT_SYSROOT_STRIP = "1"
INSANE_SKIP:${PN} += "arch ldflags file-rdeps build-deps already-stripped"

inherit package-image
