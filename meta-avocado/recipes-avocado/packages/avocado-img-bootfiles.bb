SUMMARY = "Package containing all deploy directory artifacts"
DESCRIPTION = "Collects all build artifacts from the deploy directory into a single package"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

PV = "${DISTRO_VERSION}"

# Don't create debug packages for this
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INHIBIT_PACKAGE_STRIP = "1"

# Skip architecture mismatch QA checks
INSANE_SKIP:${PN} += "arch"

do_compile[depends] += "avocado-stone:do_deploy"
do_compile[depends] += "virtual/kernel:do_deploy"

PACKAGE_ARCH = "${MACHINE_ARCH}"
PACKAGES = "${PN}"

# Default skip patterns for bootfiles collection.
#
# These exclude the three partition images the avocado-cli builds itself into
# the runtime output dir (rootfs / initramfs / var); everything else in the
# deploy dir (kernel Image, base DTBs, imx-boot, etc.) is what a SOM target
# must ship so stone bundle can assemble the boot partition.
#
# Patterns are matched as a lowercase SUBSTRING of each deploy filename, so they
# MUST be anchored to the full `avocado-image-<kind>-` basename. A bare token
# like `-var-` also matches any machine whose name contains it (e.g. every
# Variscite SOM: imx8mp-var-dart, imx93-var-som, ...), which silently strips the
# kernel Image--<...>-var-dart-<...>.bin, the imx8mp-var-dart-*.dtb device trees,
# and imx-boot from the package -- leaving their symlinks dangling and breaking
# `stone bundle` with "File 'Image' not found in any input directory".
AVOCADO_IMG_BOOTFILES_SKIP_DEFAULT = "avocado-image-rootfs avocado-image-initramfs avocado-image-var-"
# Additional skip patterns (can be extended via bbappends)
AVOCADO_IMG_BOOTFILES_SKIP_EXTRA ?= ""
# Combined skip patterns
AVOCADO_IMG_BOOTFILES_SKIP = "${AVOCADO_IMG_BOOTFILES_SKIP_DEFAULT} ${AVOCADO_IMG_BOOTFILES_SKIP_EXTRA}"

# Prevent automatic dependency detection for image packages
RDEPENDS:${PN} = ""
INHIBIT_PACKAGE_STRIP = "1"
INHIBIT_SYSROOT_STRIP = "1"
INHIBIT_DEFAULT_DEPS = "1"
SKIP_FILEDEPS = "1"
AUTO_LIBNAME_RDEPS = "0"
INSANE_SKIP:${PN} += "arch ldflags file-rdeps build-deps already-stripped dev-deps"

# Custom task to collect artifacts
python do_collect_artifacts() {
    import shutil
    import os

    deploy_dir = d.getVar('DEPLOY_DIR_IMAGE')
    workdir = d.getVar('WORKDIR')
    dest_dir = os.path.join(workdir, 'deploy-artifacts')

    # Get skip patterns from variable (space-separated)
    skip_patterns_str = d.getVar('AVOCADO_IMG_BOOTFILES_SKIP') or ''
    skip_patterns = skip_patterns_str.split()

    # Clean and create destination
    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir)
    os.makedirs(dest_dir)

    # Copy bootfiles from deploy dir, excluding files matching skip patterns
    if os.path.exists(deploy_dir):
        for item in os.listdir(deploy_dir):
            # Skip files matching any of the configured patterns
            if any(pattern in item.lower() for pattern in skip_patterns):
                bb.note(f"Skipping {item} - matches pattern in AVOCADO_IMG_BOOTFILES_SKIP")
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
    install -d ${D}

    # Copy everything from our collection
    if [ -d ${WORKDIR}/deploy-artifacts ]; then
        cp -r ${WORKDIR}/deploy-artifacts/* ${D}
    fi
}

# Package all the artifacts
FILES:${PN} = "/*"

# Skip arch QA check - some files are correctly of a different arch than the target.
INSANE_SKIP:${PN} += "arch buildpaths"
