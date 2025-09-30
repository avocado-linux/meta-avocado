DESCRIPTION = "rubikpi devicetree overlay"
LICENSE = "BSD-3-Clause"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/${LICENSE};md5=550794465ba0ec5312d6919e203a55f9"

inherit deploy

SRC_URI = "git://git@github.com/rubikpi-ai/device-tree;nobranch=1;protocol=https \
    git://git@git.codelinaro.org/clo/le/platform/vendor/opensource/camera-kernel;nobranch=1;protocol=https;destsuffix=${WORKDIR}/camera-kernel;name=camera"

SRCREV_FORMAT .= "_camera"

SRCREV_camera = "f09a43b2584655d75dea39c7fae6ef72d034c645"
SRCREV = "f5999b281d9073bba495139c14ceadc18ffa0db2"

DEPENDS += "virtual/kernel dtc-native"
do_compile[depends] += "virtual/kernel:do_shared_workdir"

S = "${WORKDIR}/git/rubikpi3"

DTC ?= "dtc"

CAMERA_INCLUDE := "${WORKDIR}/camera-kernel/camera/"
KERNEL_INCLUDE := "${STAGING_KERNEL_DIR}/include/  -I ${CAMERA_INCLUDE}"
EXTRA_OEMAKE += "DTC='${DTC}' KERNEL_INCLUDE='${KERNEL_INCLUDE}'"

do_compile() {
    oe_runmake ${EXTRA_OEMAKE} rubikpi3-overlay
}

do_deploy() {
    install -d ${DEPLOYDIR}/tech_dtbs
    install -m 0644 ${S}/*.dtbo ${DEPLOYDIR}/tech_dtbs/
}

addtask do_deploy after do_install
