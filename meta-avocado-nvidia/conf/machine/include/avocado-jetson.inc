USE_REDUNDANT_FLASH_LAYOUT_DEFAULT = "1"
ROOTFSPART_SIZE_DEFAULT = "536870912"

AVOCADO_IMAGE_INITRAMFS_TYPE = "cpio.gz"
INITRAMFS_FSTYPES = "${AVOCADO_IMAGE_INITRAMFS_TYPE}"

ROOT_FSTYPES = "squashfs tegraflash"
IMAGE_TEGRAFLASH_FS_TYPE = "squashfs"

DATAFILE = "avocado-image-var-${MACHINE}.btrfs"
IMAGE_TEGRAFLASH_DATA = "${DEPLOY_DIR_IMAGE}/avocado-image-var-${MACHINE}.btrfs"

# Extras Repo Configurations
PACKAGECONFIG:remove:pn-wpewebkit = "gbm"
DEPENDS:append:pn-wpewebkit = " libdrm"
