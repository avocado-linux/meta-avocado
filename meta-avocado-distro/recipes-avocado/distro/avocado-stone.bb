DESCRIPTION = "Create an Avocado Stone for testing a finished yocto build"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

PV = "${DISTRO_VERSION}"

PACKAGES = "${PN}"
PACKAGE_ARCH = "${MACHINE_ARCH}"

DEPENDS += " stone-native avocado-img-var avocado-img-rootfs"

# Skip other tasks
do_populate_sysroot[noexec] = "1"
do_install[noexec] = "1"
do_packagedata[noexec] = "1"
do_package[noexec] = "1"
do_package_qa[noexec] = "1"
do_package_write_rpm[noexec] = "1"

SRC_URI = "file://stone-${MACHINE_SHORT_NAME}.json"

SRC_URI:append:stone-img = " \
    file://stone-provision-img.sh \
"

SRC_URI:append:stone-sd = " \
    file://stone-provision-sd.sh \
"

SRC_URI:append:stone-usb = " \
    file://stone-provision-usb.sh \
"

inherit stone
inherit deploy

do_compile[depends] += "avocado-core:do_compile"
do_compile[depends] += "avocado-image-initramfs:do_image_complete"
do_compile[depends] += "avocado-image-rootfs:do_image_complete"
do_compile[depends] += "avocado-image-var:do_deploy"
do_compile[depends] += "virtual/kernel:do_deploy"

do_deploy[nostamp] = "1"
do_stone_validate[nostamp] = "1"
do_stone_bundle[nostamp] = "1"
do_stone_provision[nostamp] = "1"

do_configure() {
    # Clean out existing stone directory
    if [ -d "${DEPLOY_DIR}/stone" ]; then
        rm -rf "${DEPLOY_DIR}/stone"
    fi
}

do_deploy() {
    install -d ${DEPLOYDIR}
    install -m 0644 ${WORKDIR}/stone-${MACHINE_SHORT_NAME}.json ${DEPLOYDIR}/stone-${MACHINE_SHORT_NAME}.json
}

do_deploy:append:stone-sd() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/stone-provision-sd.sh ${DEPLOYDIR}/stone-provision-sd.sh
}

do_deploy:append:stone-usb() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/stone-provision-usb.sh ${DEPLOYDIR}/stone-provision-usb.sh
}

do_deploy:append:stone-img() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/stone-provision-img.sh ${DEPLOYDIR}/stone-provision-img.sh
}

do_stone_validate() {
    stone \
        validate \
        -m "${DEPLOY_DIR_IMAGE}/stone-${MACHINE_SHORT_NAME}.json" \
        -i "${DEPLOY_DIR_IMAGE}"
}

do_stone_bundle() {
    stone \
        bundle \
        --os-release "${DEPLOY_DIR_IMAGE}/os-release" \
        -m "${DEPLOY_DIR_IMAGE}/stone-${MACHINE_SHORT_NAME}.json" \
        -i "${DEPLOY_DIR_IMAGE}" \
        -o "${DEPLOY_DIR}/stone/os-bundle.aos" \
        --build-dir "${DEPLOY_DIR}/stone"
}

do_stone_provision() {
    ${@'AVOCADO_PROVISION_PROFILE="' + d.getVar('AVOCADO_PROVISION_PROFILE') + '"' if d.getVar('AVOCADO_PROVISION_PROFILE') else ''} stone \
        provision \
        -i "${DEPLOY_DIR}/stone"
}

addtask configure after do_patch before do_compile
addtask deploy after do_compile before do_build

# Stone tasks run after deploy
# Note: do_package is noexec so we can't use "before do_package"
# Instead, chain tasks properly and make do_build depend on them
addtask stone_validate after do_deploy
addtask stone_bundle after do_stone_validate
addtask stone_provision after do_stone_bundle

# By default, do_build depends on do_stone_bundle (validate + bundle)
# Machine layers can override this to only run validation
STONE_BUILD_TASK ?= "do_stone_bundle"
do_build[depends] += "${PN}:${STONE_BUILD_TASK}"
