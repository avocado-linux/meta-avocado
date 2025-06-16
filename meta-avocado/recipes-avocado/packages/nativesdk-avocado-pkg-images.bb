SUMMARY = "Package containing all deploy directory artifacts"
DESCRIPTION = "Collects all build artifacts from the deploy directory into a single package"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

# Don't create debug packages for this
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INHIBIT_PACKAGE_STRIP = "1"

do_compile[depends] += "avocado-image-initramfs:do_image_complete"
do_compile[depends] += "avocado-image-rootfs:do_image_complete"
do_compile[depends] += "avocado-image-var:do_deploy"
do_compile[depends] += "${@bb.utils.contains('MACHINE_FEATURES', 'genimage', 'avocado-image-genimage:do_deploy', '', d)}"
do_compile[depends] += "virtual/kernel:do_deploy"

PACKAGE_ARCH = "${SDK_ARCH}-${SDKPKGSUFFIX}"

# Custom task to collect artifacts
python do_collect_artifacts() {
    import shutil
    import os

    deploy_dir = d.getVar('DEPLOY_DIR_IMAGE')
    workdir = d.getVar('WORKDIR')
    dest_dir = os.path.join(workdir, 'deploy-artifacts')

    # Clean and create destination
    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir)
    os.makedirs(dest_dir)

    # Copy everything from deploy dir
    if os.path.exists(deploy_dir):
        for item in os.listdir(deploy_dir):
            # Skip avocado-image-genimage files
            if item.startswith('avocado-image-genimage'):
                continue

            src = os.path.join(deploy_dir, item)
            dst = os.path.join(dest_dir, item)

            if os.path.islink(src):
                # Preserve symlinks
                link_target = os.readlink(src)
                os.symlink(link_target, dst)
            elif os.path.isfile(src):
                shutil.copy2(src, dst)
            elif os.path.isdir(src):
                shutil.copytree(src, dst, symlinks=True)

    bb.note(f"Collected artifacts from {deploy_dir} to {dest_dir}")
}

# Add the task to the build pipeline
addtask collect_artifacts after do_compile before do_install

do_install() {
    # Install collected artifacts
    install -d ${D}/deploy

    # Copy everything from our collection
    if [ -d ${WORKDIR}/deploy-artifacts ]; then
        cp -r ${WORKDIR}/deploy-artifacts/* ${D}/deploy
    fi
}

# Package all the artifacts
FILES:${PN} = "/deploy/*"

# Skip arch QA check - some files are correctly of a different arch than the target.
INSANE_SKIP:${PN} += "arch buildpaths"
