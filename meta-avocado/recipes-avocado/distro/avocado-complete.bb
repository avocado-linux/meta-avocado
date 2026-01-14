SUMMARY = "Meta-target to build Avocado OS images, extensions, and extra packages"
LICENSE = "Apache-2.0"

inherit avocado-repo-map

# Ensure build task runs after dependencies
do_compile[depends] += "avocado-distro:do_build"
do_compile[depends] += "avocado-sdk:do_build"

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

# Ensure these recipes are excluded from world builds
EXCLUDE_FROM_WORLD = "1"

# Custom task to write completion marker and generate repo map
python do_compile() {
    import os
    import bb

    deploy_dir_rpm = d.getVar('DEPLOY_DIR_RPM')
    pn = d.getVar('PN')

    # Write completion marker
    if deploy_dir_rpm and os.path.isdir(deploy_dir_rpm):
        import datetime
        marker_path = os.path.join(deploy_dir_rpm, 'avocado-build.done')
        with open(marker_path, 'w') as f:
            f.write(f"{datetime.datetime.now().isoformat()}: Build completed for {pn}\n")
        bb.note(f"Writing build completion marker to {marker_path}")
    else:
        bb.warn(f"DEPLOY_DIR_RPM not set or directory does not exist: {deploy_dir_rpm}")

    # Generate the repo map file
    bb.build.exec_func('do_create_repo_map', d)
}

# Force the compile task to be part of the build pipeline
addtask compile after do_configure before do_build
