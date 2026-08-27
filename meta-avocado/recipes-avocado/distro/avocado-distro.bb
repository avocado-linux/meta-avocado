SUMMARY = "Meta-target to build Avocado OS core images and nativesdk toolchain"
LICENSE = "Apache-2.0"

PV = "${DISTRO_VERSION}"

inherit avocado-repo-map avocado-multikernel

# Ensure compile task runs after dependencies
do_compile[depends] += "avocado-core:do_build"
do_compile[depends] += "avocado-stone:do_build"
do_compile[depends] += "avocado-pkg-extra:do_build"
do_compile[depends] += "avocado-pkg-sdk-all:do_build"

# Both shipped images reach this build only through avocado-stone, which asks
# for do_image_complete (avocado-stone.bb:40-41). That is enough to produce each
# image and not enough to produce its SBOM: create-spdx-image-3.0 attaches
# do_create_image_spdx and do_create_image_sbom_spdx before do_build, so on a
# distro build both sit one task past everything anything requests. The
# flattened per-image document - the one with an Sbom root listing what shipped,
# rather than a tree of per-recipe documents to reassemble - therefore never
# exists for either.
#
# avocado-image-var is deliberately absent: it inherits deploy rather than
# image, so it carries no SPDX image tasks and has no equivalent gap.
#
# Asking for do_build rather than for the SPDX tasks by name keeps this correct
# when SPDX is off: do_build is an aggregator, so a build without the class
# inherited gains nothing, and one with it gains exactly the two tasks.
do_compile[depends] += "avocado-image-rootfs:do_build"
do_compile[depends] += "avocado-image-initramfs:do_build"

# Skip other tasks
do_configure[noexec] = "1"
do_fetch[noexec] = "1"
do_unpack[noexec] = "1"
do_patch[noexec] = "1"
do_install[noexec] = "1"
do_packagedata[noexec] = "1"
do_package[noexec] = "1"
do_package_qa[noexec] = "1"
do_package_write_rpm[noexec] = "1"
do_populate_sysroot[noexec] = "1"

do_compile[nostamp] = "1"
do_build[nostamp] = "1"

# Generate repo map after all packages are built
python do_compile() {
    bb.build.exec_func('do_create_repo_map', d)
}

# Force the compile task to be part of the build pipeline
addtask compile after do_configure before do_build

# Ensure these recipes are excluded from world builds
EXCLUDE_FROM_WORLD = "1"
