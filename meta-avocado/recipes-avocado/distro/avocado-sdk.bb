SUMMARY = "Meta-target to build Avocado OS sdk packages"
LICENSE = "Apache-2.0"

PV = "${SDK_VERSION}"

inherit avocado-repo-map

# Ensure compile task runs after dependencies
do_compile[depends] += "avocado-pkg-sdk:do_build"
do_compile[depends] += "avocado-pkg-sdk-extra:do_build"

# Skip other tasks
do_configure[noexec] = "1"
do_fetch[noexec] = "1"
do_unpack[noexec] = "1"
do_patch[noexec] = "1"
do_install[noexec] = "1"
do_populate_sysroot[noexec] = "1"
do_packagedata[noexec] = "1"
do_package[noexec] = "1"
do_package_qa[noexec] = "1"
do_package_write_rpm[noexec] = "1"

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
