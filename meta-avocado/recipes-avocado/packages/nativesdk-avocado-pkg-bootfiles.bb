SUMMARY = "Copy boot files to /opt/avocado/bootfiles"
LICENSE = "Apache-2.0"

IMAGE_BOOTFILES ?= ""
AVOCADO_PKG_BOOTFILES_EXTRA ?= ""
AVOCADO_IMAGES_INSTALL_PREFIX = "${SDKPATHNATIVE}/images"
FILES:${PN} = "${AVOCADO_IMAGES_INSTALL_PREFIX}"
PACKAGES = "${PN}"
PACKAGE_ARCH = "${SDK_ARCH}-${SDKPKGSUFFIX}"

# Let bitbake know we need these files before we can package
do_fetch[noexec] = "1"
do_unpack[noexec] = "1"
do_patch[noexec] = "1"
do_configure[noexec] = "1"
do_compile[noexec] = "1"

# Make sure the bootfiles are created before we try to package them
do_install[depends] += "avocado-image-rootfs:do_image_complete"

fakeroot do_install() {
    # Create the directory structure for installation
    install -d ${D}${AVOCADO_IMAGES_INSTALL_PREFIX}

    # Get the list of boot files from variables
    local_bootfiles=""
    if [ -n "${IMAGE_BOOT_FILES}" ]; then
        local_bootfiles="${IMAGE_BOOT_FILES}"
    fi

    if [ -n "${AVOCADO_PKG_BOOTFILES_EXTRA}" ]; then
        if [ -n "${local_bootfiles}" ]; then
            local_bootfiles="${local_bootfiles} ${AVOCADO_PKG_BOOTFILES_EXTRA}"
        else
            local_bootfiles="${AVOCADO_PKG_BOOTFILES_EXTRA}"
        fi
    fi

    if [ -z "${local_bootfiles}" ]; then
        bbnote "Neither IMAGE_BOOT_FILES nor AVOCADO_PKG_BOOTFILES_EXTRA are set. No files will be packaged."
        return
    fi

    for bootfile in ${local_bootfiles}; do
        # Handle entries of the form "file1;file2" by grabbing just the part before the semicolon
        src_file=$(echo "${bootfile}" | cut -d';' -f1)
        if [ ! -e "${DEPLOY_DIR_IMAGE}/${src_file}" ]; then
            bbnote "Source file ${DEPLOY_DIR_IMAGE}/${src_file} does not exist. Skipping."
            continue
        fi

        # Install the file with explicit permissions
        install -m 0644 ${DEPLOY_DIR_IMAGE}/${src_file} ${D}${AVOCADO_IMAGES_INSTALL_PREFIX}/$(basename ${src_file})
    done
}

addtask do_install after do_compile before do_package
