inherit image-avocado-qcom-deploy

do_deploy_fixup:append() {
    # copy splash.img
    if [ -f ${DEPLOY_DIR_IMAGE}/splash.img ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/splash.img splash.img
    fi

    # copy rubikpi_config.img
    if [ -f ${DEPLOY_DIR_IMAGE}/rubikpi_config.img ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/rubikpi_config.img rubikpi_config.img
    fi

    # copy devcfg_full.img
    if [ -f ${DEPLOY_DIR_IMAGE}/devcfg_full.img ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/devcfg_full.img devcfg_full.img
    fi

    # copy rubikpi_dtso.img
    if [ -f ${DEPLOY_DIR_IMAGE}/rubikpi_dtso.img ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/rubikpi_dtso.img rubikpi_dtso.img
    fi

    # copy RubikPi3_CDT.bin
    if [ -f ${DEPLOY_DIR_IMAGE}/RubikPi3_CDT.bin ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/RubikPi3_CDT.bin RubikPi3_CDT.bin
    fi

    # copy initramfs
    if [ -f ${DEPLOY_DIR_IMAGE}/${INITRAMFS_IMAGE}-${MACHINE}.cpio.gz ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/${INITRAMFS_IMAGE}-${MACHINE}.cpio.gz ${INITRAMFS_IMAGE}-${MACHINE}.cpio.gz
    fi

    # copy linuxaa64.efi.stub
    if [ -f ${DEPLOY_DIR_IMAGE}/linuxaa64.efi.stub ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/linuxaa64.efi.stub linuxaa64.efi.stub
    fi

    # copy avocado-image-var BTRFS image
    if [ -f ${DEPLOY_DIR_IMAGE}/avocado-image-var-${MACHINE_SHORT_NAME}.btrfs ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/avocado-image-var-${MACHINE_SHORT_NAME}.btrfs avocado-image-var-${MACHINE_SHORT_NAME}.btrfs
    fi

    # create final provision image
    tar -caf ${DEPLOY_DIR_IMAGE}/${IMAGE_NAME}.ufs.tar.gz -C ${DEPLOY_DIR_IMAGE} ${IMAGE_BASENAME}
}
