SUMMARY = "Meta-target to build Avocado OS images, extensions, and extra packages"
LICENSE = "Apache-2.0"

# Ensure build task runs after dependencies
do_compile[depends] += "avocado-distro:do_build"
do_compile[depends] += "avocado-sdk:do_build"

# Skip other tasks
do_configure[noexec] = "1"
do_fetch[noexec] = "1"
do_unpack[noexec] = "1"
do_patch[noexec] = "1"
do_populate_sysroot[noexec] = "1"
do_packagedata[noexec] = "1"
do_package[noexec] = "1"
do_package_qa[noexec] = "1"
do_package_write_rpm[noexec] = "1"

do_compile[nostamp] = "1"
do_write_completion_marker[nostamp] = "1"

# Ensure these recipes are excluded from world builds
EXCLUDE_FROM_WORLD = "1"

# Custom task to write completion marker
do_compile() {
    # Write a completion marker file to the deploy directory
    # This triggers repository monitoring and metadata updates
    if [ -n "${DEPLOY_DIR_RPM}" ] && [ -d "${DEPLOY_DIR_RPM}" ]; then
        echo "$(date -Iseconds): Build completed for ${PN}" > "${DEPLOY_DIR_RPM}/avocado-build.done"
        echo "Writing build completion marker to ${DEPLOY_DIR_RPM}/avocado-build.done"
    else
        bbwarn "DEPLOY_DIR_RPM not set or directory does not exist: ${DEPLOY_DIR_RPM}"
    fi
}

# Force the compile task to be part of the build pipeline
addtask compile after do_configure before do_build
