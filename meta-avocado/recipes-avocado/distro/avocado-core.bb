SUMMARY = "Meta-target to build Avocado OS core images and nativesdk toolchain"
LICENSE = "Apache-2.0"

# Ensure compile task runs after dependencies
do_compile[depends] += "avocado-image-initramfs:do_image_complete"
do_compile[depends] += "avocado-image-rootfs:do_image_complete"
do_compile[depends] += "avocado-image-var:do_deploy"
do_compile[depends] += "${@bb.utils.contains('MACHINE_FEATURES', 'genimage', 'avocado-image-genimage:do_deploy', '', d)}"
do_compile[depends] += "avocado-pkg-sdk:do_build"

# Skip other tasks
do_packagedata[noexec] = "1"
do_configure[noexec] = "1"
do_fetch[noexec] = "1"
do_unpack[noexec] = "1"
do_patch[noexec] = "1"
do_install[noexec] = "1"
do_package[noexec] = "1"
do_populate_sysroot[noexec] = "1"
do_package_write_rpm[noexec] = "1"

# Ensure these recipes are excluded from world builds
EXCLUDE_FROM_WORLD = "1"
