SUMMARY = "Meta-target to build Avocado OS images, extensions, and extra packages"
LICENSE = "Apache-2.0"

# Ensure compile task runs after dependencies
do_compile[depends] += "avocado-core:do_build"
do_compile[depends] += "avocado-pkg-extra:do_build"
do_compile[depends] += "avocado-pkg-sdk-extra:do_build"

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
