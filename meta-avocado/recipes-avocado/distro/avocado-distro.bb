SUMMARY = "Meta-target to build Avocado OS core images and nativesdk toolchain"
LICENSE = "Apache-2.0"

DEPENDS += "stone-native"

# Ensure compile task runs after dependencies
do_compile[depends] += "avocado-core:do_build"
do_compile[depends] += "avocado-pkg-extra:do_build"
do_compile[depends] += "${VIRTUAL-RUNTIME_avocado-sdk-metadata}:do_deploy"

# Skip other tasks
do_configure[noexec] = "1"
do_fetch[noexec] = "1"
do_unpack[noexec] = "1"
do_patch[noexec] = "1"
# do_packagedata[noexec] = "1"
# do_package[noexec] = "1"
do_package_qa[noexec] = "1"
do_package_write_rpm[noexec] = "1"

do_build[nostamp] = "1"
do_stone_validate[nostamp] = "1"

# Ensure these recipes are excluded from world builds
EXCLUDE_FROM_WORLD = "1"

do_stone_validate:stone-validate() {
    stone \
        validate \
        -m "${DEPLOY_DIR_IMAGE}/stone-${MACHINE_SHORT_NAME}.json" \
        -i "${DEPLOY_DIR_IMAGE}"
}

do_stone_validate() {
    bbnote "Stone validate is not added to MACHINEOVERRIDES for ${MACHINE_SHORT_NAME}"
}

addtask stone_validate after do_compile before do_package
