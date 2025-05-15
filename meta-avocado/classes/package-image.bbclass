# Class to package a rootfs image into a package

AVOCADO_PKG_IMG_NAME ?= ""
AVOCADO_PKG_IMG_RECIPE ?= ""

PACKAGE_ARCH ?= "${SDK_ARCH}-${SDKPKGSUFFIX}"
PACKAGES = "${PN}"
AVOCADO_IMAGES_INSTALL_PREFIX = "${SDKPATHNATIVE}/images"
AVOCADO_PKG_IMG_DEPTASK ?= "do_image_complete"
python () {
    if not d.getVar('AVOCADO_PKG_IMG_NAME') or d.getVar('AVOCADO_PKG_IMG_NAME') == "":
        bb.fatal("AVOCADO_PKG_IMG_NAME must be set in the recipe using this class.")
    if not d.getVar('AVOCADO_PKG_IMG_RECIPE') or d.getVar('AVOCADO_PKG_IMG_RECIPE') == "":
        bb.fatal("AVOCADO_PKG_IMG_RECIPE must be set in the recipe using this class.")
    d.setVarFlag('do_compile', 'depends', d.getVar('AVOCADO_PKG_IMG_RECIPE') + ":" + d.getVar('AVOCADO_PKG_IMG_DEPTASK'))
}

do_install() {
    install -d ${D}${AVOCADO_IMAGES_INSTALL_PREFIX}
    install ${DEPLOY_DIR_IMAGE}/${AVOCADO_PKG_IMG_NAME} ${D}${AVOCADO_IMAGES_INSTALL_PREFIX}/${AVOCADO_PKG_IMG_NAME}
}

FILES:${PN} = "${AVOCADO_IMAGES_INSTALL_PREFIX}/${AVOCADO_PKG_IMG_NAME}"
