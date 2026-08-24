MACHINE_FEATURES:append = " optee"

# Jetson consoles are on the Tegra Combined UART with no virtual console, so
# OE-core's `enable getty@.service` preset can only ever fail. Shipped from the
# shared include rather than per-machine: it applies to every Jetson, devkit or
# carrier. See recipes-core/systemd/systemd-jetson-masks_1.0.bb.
MACHINE_ESSENTIAL_EXTRA_RDEPENDS += "systemd-jetson-masks"

STONE_PROVISIONING ?= "tegraflash"
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

# Var partition is mounted dynamically by avocado-tegra-init using PARTLABEL discovery
# on the same disk as rootfs. This handles NVMe, eMMC, and SD boot media transparently.
AVOCADO_VAR_PART_DEV = "none"

DATAFILE = "avocado-image-var-${MACHINE_SHORT_NAME}.btrfs"
IMAGE_TEGRAFLASH_DATA = "${DEPLOY_DIR_IMAGE}/avocado-image-var-${MACHINE_SHORT_NAME}.btrfs"

# Wrynose oe-core (commit 76316c765d) added a fatal check on every entry in
# the post-first dot of IMAGE_FSTYPES (image_types.bbclass:imagetypes_getdepends).
# meta-tegra's IMAGE_FSTYPES += "tegraflash.tar.zst" sets `tegraflash.tar` as
# the multi-dot basetype (see IMAGE_CMD:tegraflash.tar in image_types_tegra.bbclass),
# but split_types in image_types.bbclass naively splits on every dot and
# treats `tar` as a conversion — triggering "No CONVERSION_CMD defined for
# subtype 'tar'" on every image parse. The actual build flow uses image.bbclass's
# _image_base_type which correctly walks CONVERSIONTYPES, so `tar` is never
# in the conversion chain at run time. Provide a CONVERSION_CMD:tar shim so
# the parse check passes; the body would only be invoked if `tar` were also
# added to CONVERSIONTYPES (which we deliberately don't do — that would change
# _image_base_type's basetype resolution and break tegraflash.tar).
CONVERSION_CMD:tar = "tar --sort=name --format=posix --numeric-owner -cf ${IMAGE_NAME}.${type}.tar -C ${WORKDIR} ${IMAGE_NAME}.${type}"

# Extras Repo Configurations
PACKAGECONFIG:remove:pn-wpewebkit = "gbm"
DEPENDS:append:pn-wpewebkit = " libdrm"
DEPENDS:append:pn-chromium-ozone-wayland = " virtual/libgbm"