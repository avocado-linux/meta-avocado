SWUPDATE_IMAGES:remove = " \
	${SYNA_IMAGE_NAME}-${MACHINE} \
"

SWUPDATE_IMAGES:append = " \
	${SYNA_IMAGE_NAME}-${GRINN_MACHINE} \
"

python () {
    image = d.expand('${SYNA_IMAGE_NAME}-${GRINN_MACHINE}')
    d.setVarFlag('SWUPDATE_IMAGES_FSTYPES', image, '.rootfs.ext4.gz')
}

