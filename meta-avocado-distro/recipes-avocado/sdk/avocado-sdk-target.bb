DESCRIPTION = "Avocado SDK target specific packages and dependencies"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"


PACKAGES = "${PN}"
PACKAGE_ARCH = "${SDKPKGARCH}"
INSANE_SKIP:${PN} = "file-rdeps build-deps"

SRC_URI = "\
  file://avocado-build-${MACHINE_SHORT_NAME} \
  file://avocado-provision-${MACHINE_SHORT_NAME} \
  file://stone-${MACHINE_SHORT_NAME}.json \
"

inherit deploy

FILES:${PN}   = "\
  ${SDKPATHNATIVE}${bindir}/avocado-build-${MACHINE_SHORT_NAME} \
  ${SDKPATHNATIVE}${bindir}/avocado-provision-${MACHINE_SHORT_NAME} \
  ${SDKPATHNATIVE}/stone \
"

do_install() {
    install -d ${D}${SDKPATHNATIVE}${bindir}
    install -d ${D}${SDKPATHNATIVE}/stone
    install -m 0755 ${WORKDIR}/avocado-build-${MACHINE_SHORT_NAME} ${D}${SDKPATHNATIVE}${bindir}
    install -m 0755 ${WORKDIR}/avocado-provision-${MACHINE_SHORT_NAME} ${D}${SDKPATHNATIVE}${bindir}
    install -m 0755 ${WORKDIR}/stone-${MACHINE_SHORT_NAME}.json ${D}${SDKPATHNATIVE}/stone/stone-${MACHINE_SHORT_NAME}.json
}

do_deploy() {
    install -d ${DEPLOYDIR}
    install -m 0755 ${WORKDIR}/stone-${MACHINE_SHORT_NAME}.json ${DEPLOYDIR}/stone-${MACHINE_SHORT_NAME}.json
}

addtask deploy before do_package after do_install
