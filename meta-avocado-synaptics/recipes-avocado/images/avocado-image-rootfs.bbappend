# Ensure erofs-lz4 is produced before synaimg so our IMAGE_CMD append can
# copy the deployed erofs file into rootfs.subimg.
IMAGE_TYPEDEP:synaimg:append:avocado-synaptics = " erofs-lz4"

# Ensure avocado-image-var is fully deployed before do_image_synaimg runs so
# its btrfs image is available in DEPLOY_DIR_IMAGE.
python () {
    if 'avocado-synaptics' in (d.getVar('OVERRIDES') or '').split(':'):
        d.appendVarFlag('do_image_synaimg', 'depends',
                        ' avocado-image-var:do_deploy')
}

# image.bbclass builds do_image_synaimg by compiling IMAGE_CMD:synaimg into a
# task via d.setVar(task, ...) in a Python anonymous function. Any shell-function
# appends to do_image_synaimg set in bbappend files are silently dropped because
# d.setVar() overwrites them at that stage. The correct hook point is
# IMAGE_CMD:synaimg:append, which is resolved by localdata.getVar("IMAGE_CMD")
# inside that same Python function and inlined into the compiled task body.
#
# This append:
#  1. Replaces the vendor-generated ext4 rootfs.subimg with the Avocado
#     erofs-lz4 rootfs image.
#  2. Replaces the vendor-generated home_s.subimg with the Avocado btrfs var
#     image (avocado-image-var) as var_s.subimg.

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

    # Replace the vendor home partition image with the Avocado btrfs var image.
    var_src="${DEPLOY_DIR_IMAGE}/avocado-image-var${IMAGE_MACHINE_SUFFIX}.btrfs"

    if [ ! -f "${var_src}" ]; then
        bbfatal "Avocado btrfs var image not found: ${var_src}"
    fi

    bbnote "avocado: replacing home_s.subimg with avocado-image-var${IMAGE_MACHINE_SUFFIX}.btrfs as var_s.subimg"

    # Convert the btrfs var image to Android sparse image format.
    rm -f "${DEPLOY_DIR_IMAGE}/var_s.subimg"
    img2simg "${var_src}" "${DEPLOY_DIR_IMAGE}/var_s.subimg" 4096

    # Remove vendor home images from SYNAIMG and install var_s.subimg.
    rm -f "${DEPLOY_DIR_IMAGE}/${SYNAIMG_DEPLOY_SUBDIR}/home.subimg.gz"
    rm -f "${DEPLOY_DIR_IMAGE}/${SYNAIMG_DEPLOY_SUBDIR}/home_s.subimg"
    cp "${DEPLOY_DIR_IMAGE}/var_s.subimg" \
        "${DEPLOY_DIR_IMAGE}/${SYNAIMG_DEPLOY_SUBDIR}/var_s.subimg"

    # Update emmc_image_list: replace home entry (either .gz or sparse) with var_s.subimg.
    sed -i 's/^home\.subimg\.gz/var_s.subimg/' \
        "${DEPLOY_DIR_IMAGE}/${SYNAIMG_DEPLOY_SUBDIR}/emmc_image_list"
    sed -i 's/^home_s\.subimg/var_s.subimg/' \
        "${DEPLOY_DIR_IMAGE}/${SYNAIMG_DEPLOY_SUBDIR}/emmc_image_list"
}
