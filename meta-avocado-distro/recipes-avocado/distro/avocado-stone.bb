DESCRIPTION = "Create an Avocado Stone for testing a finished yocto build"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

PACKAGES = "${PN}"
PACKAGE_ARCH = "${MACHINE_ARCH}"

DEPENDS += " stone-native"

# Skip other tasks
do_configure[noexec] = "1"
do_package_qa[noexec] = "1"
do_package_write_rpm[noexec] = "1"

do_deploy[depends] += "avocado-core:do_build"

SRC_URI = "file://stone-${MACHINE_SHORT_NAME}.json"

inherit stone
inherit deploy

do_stone_validate[nostamp] = "1"

do_deploy() {
    install -d ${DEPLOYDIR}
    install -m 0644 ${WORKDIR}/stone-${MACHINE_SHORT_NAME}.json ${DEPLOYDIR}/stone-${MACHINE_SHORT_NAME}.json
}

do_stone_validate:stone-validate() {
    stone \
        validate \
        -m "${DEPLOY_DIR_IMAGE}/stone-${MACHINE_SHORT_NAME}.json" \
        -i "${DEPLOY_DIR_IMAGE}"
}

do_stone_validate() {
    bbnote "Stone validate is not added to MACHINEOVERRIDES for ${MACHINE_SHORT_NAME}"
}

do_stone_provision() {
    bbnote "Provisioning stone for ${MACHINE_SHORT_NAME}"
}

addtask deploy after do_compile before do_stone_validate
addtask stone_validate after do_deploy before do_package
addtask stone_provision after do_stone_validate before do_package
