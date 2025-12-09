DESCRIPTION = "Avocado tegraflash Image Package"
LICENSE = "Apache-2.0"

PV = "${DISTRO_VERSION}"

AVOCADO_PKG_IMG_RECIPE = "avocado-image-rootfs"
AVOCADO_PKG_IMG_NAME = "${AVOCADO_PKG_IMG_RECIPE}-${MACHINE_SHORT_NAME}.tegraflash.tar.gz"

inherit package-image

do_compile() {
    # Create temporary directory for unpacking and modifying the tegraflash archive
    TEMP_DIR="${DEPLOY_DIR_IMAGE}/tegraflash_temp"
    rm -rf "${TEMP_DIR}"
    mkdir -p "${TEMP_DIR}"

    # Path to the original tegraflash archive
    ARCHIVE_PATH="${DEPLOY_DIR_IMAGE}/${AVOCADO_PKG_IMG_NAME}"

    if [ ! -f "${ARCHIVE_PATH}" ]; then
        bbfatal "Tegraflash archive not found: ${ARCHIVE_PATH}"
    fi

    # Unpack the tegraflash archive
    bbnote "Unpacking tegraflash archive: ${ARCHIVE_PATH}"
    tar -xzf "${ARCHIVE_PATH}" -C "${TEMP_DIR}"

    # Remove rootfs, initramfs, and var files
    bbnote "Removing rootfs, initramfs, and var files from tegraflash archive"

    # Remove rootfs files (typically .ext4, .img files that contain rootfs)
    find "${TEMP_DIR}" -name "avocado-image-rootfs*" -delete

    # Remove var partition files
    find "${TEMP_DIR}" -name "avocado-image-var*" -delete

    # Copy swupdate scripts
    cp ${DEPLOY_DIR_IMAGE}/*-pre.sh ${TEMP_DIR}/
    cp ${DEPLOY_DIR_IMAGE}/*-post.sh ${TEMP_DIR}/

    # Backup original archive
    mv "${ARCHIVE_PATH}" "${ARCHIVE_PATH}.backup"

    # Recompress the modified archive
    bbnote "Recompressing modified tegraflash archive"
    cd "${TEMP_DIR}"
    # Use find to include all files including hidden ones, excluding . and ..
    find . -mindepth 1 -print0 | tar -czf "${ARCHIVE_PATH}" --null -T -
    cd "${WORKDIR}"

    # Clean up temporary directory and backup file
    rm -rf "${TEMP_DIR}"
    rm -f "${ARCHIVE_PATH}.backup"

    bbnote "Successfully modified tegraflash archive: ${ARCHIVE_PATH}"
}

# Ensure do_compile runs after the tegraflash image is built but before do_install
do_compile[depends] += "${AVOCADO_PKG_IMG_RECIPE}:do_image_tegraflash"
addtask do_compile after do_unpack before do_install
