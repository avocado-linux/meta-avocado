STONE_PROVISIONING ?= "tegraflash peridio"
USE_REDUNDANT_FLASH_LAYOUT_DEFAULT = "1"
PREFERRED_PROVIDER_virtual/kernel = "linux-yocto"
ROOTFSPART_SIZE_DEFAULT = "536870912"
TEGRAFLASH_NO_INTERNAL_STORAGE = "1"

AVOCADO_IMAGE_INITRAMFS_TYPE = "cpio.gz"
# Also produce cpio.gz.cboot for the A_kernel partition (boot.img)
INITRAMFS_FSTYPES = "${AVOCADO_IMAGE_INITRAMFS_TYPE} cpio.gz.cboot"
IMAGE_TEGRAFLASH_KERNEL = "${DEPLOY_DIR_IMAGE}/${INITRD_IMAGE}-${MACHINE_SHORT_NAME}.cpio.gz.cboot"

# Removed tegraflash from ROOT_FSTYPES - BSP files are now deployed separately
# via tegraflash-bsp recipe and referenced in stone manifests
ROOT_FSTYPES = "erofs-lz4"

# Ensure tegraflash-bsp is deployed for provisioning
# Note: tegra-espimage and tos-optee are image/deploy recipes without do_populate_sysroot
# They are built via explicit task dependencies in avocado-stone.bbappend
EXTRA_IMAGEDEPENDS += "tegraflash-bsp"

DATAFILE = "avocado-image-var-${MACHINE_SHORT_NAME}.btrfs"
IMAGE_TEGRAFLASH_DATA = "${DEPLOY_DIR_IMAGE}/avocado-image-var-${MACHINE_SHORT_NAME}.btrfs"

# Extras Repo Configurations
PACKAGECONFIG:remove:pn-wpewebkit = "gbm"
DEPENDS:append:pn-wpewebkit = " libdrm"
DEPENDS:append:pn-chromium-ozone-wayland = " virtual/libgbm"