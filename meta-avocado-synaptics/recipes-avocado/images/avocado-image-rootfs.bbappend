# Ensure erofs-lz4 is produced before synaimg so our IMAGE_CMD append can
# copy the deployed erofs file into rootfs.subimg.
IMAGE_TYPEDEP:synaimg:append:avocado-synaptics = " erofs-lz4"

# image.bbclass builds do_image_synaimg by compiling IMAGE_CMD:synaimg into a
# task via d.setVar(task, ...) in a Python anonymous function. Any shell-function
# appends to do_image_synaimg set in bbappend files are silently dropped because
# d.setVar() overwrites them at that stage. The correct hook point is
# IMAGE_CMD:synaimg:append, which is resolved by localdata.getVar("IMAGE_CMD")
# inside that same Python function and inlined into the compiled task body.
#
# This append replaces the vendor-generated ext4 rootfs.subimg with the Avocado
# erofs-lz4 rootfs image so that the SYNAIMG directory used for provisioning
# contains the correct (erofs) filesystem type.

IMAGE_CMD:synaimg:append:avocado-synaptics () {
    erofs_src="${IMGDEPLOYDIR}/${IMAGE_NAME}.erofs-lz4"

    if [ ! -f "${erofs_src}" ]; then
        bbfatal "Avocado erofs-lz4 rootfs image not found: ${erofs_src}"
    fi

    bbnote "avocado: replacing ext4 rootfs.subimg with ${IMAGE_NAME}.erofs-lz4"

    # Replace the ext4 rootfs.subimg with the Avocado erofs-lz4 image.
    cp "${erofs_src}" "${DEPLOY_DIR_IMAGE}/rootfs.subimg"

    # Regenerate rootfs.subimg.gz in SYNAIMG from the erofs image.
    gzip -1 -c "${DEPLOY_DIR_IMAGE}/rootfs.subimg" \
        > "${DEPLOY_DIR_IMAGE}/${SYNAIMG_DEPLOY_SUBDIR}/rootfs.subimg.gz"

    # Convert rootfs.subimg to Android sparse image format.
    # rootfs.subimg must exist first so img2simg can read it.
    rm -f "${DEPLOY_DIR_IMAGE}/rootfs_s.subimg"
    img2simg "${DEPLOY_DIR_IMAGE}/rootfs.subimg" \
        "${DEPLOY_DIR_IMAGE}/rootfs_s.subimg" 4096
    cp "${DEPLOY_DIR_IMAGE}/rootfs_s.subimg" \
        "${DEPLOY_DIR_IMAGE}/${SYNAIMG_DEPLOY_SUBDIR}/rootfs_s.subimg"

    # Update emmc_image_list to reference rootfs_s.subimg instead of
    # rootfs.subimg.gz so the provisioning tool flashes the correct image.
    sed -i 's/^rootfs\.subimg\.gz/rootfs_s.subimg/' \
        "${DEPLOY_DIR_IMAGE}/${SYNAIMG_DEPLOY_SUBDIR}/emmc_image_list"
}
