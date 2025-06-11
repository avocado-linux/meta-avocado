DESCRIPTION = "Avocado initramfs image"
LICENSE = "Apache-2.0"

inherit image

PACKAGE_ARCH = "${MACHINE_ARCH}"

export IMAGE_BASENAME = "${MLPREFIX}avocado-image-initramfs"
IMAGE_NAME_SUFFIX ?= ""
EXTRA_INITRAMFS_FEATURES ??= ""
IMAGE_FEATURES = "${EXTRA_INITRAMFS_FEATURES}"
IMAGE_LINGUAS = ""
IMAGE_ROOTFS_EXTRA_SPACE = "0"
INITRAMFS_MAXSIZE = ""

IMAGE_INSTALL = "packagegroup-avocado-initramfs ${INITRAMFS_IMAGE_EXTRA_INSTALL}"
IMAGE_INSTALL:remove = "kernel-image kernel-devicetree"

IMAGE_FSTYPES = "${INITRAMFS_FSTYPES}"
IMAGE_FSTYPES ??= "cpio.zst"
ZSTD_COMPRESSION_LEVEL ?= "3"

# Strip all binaries
INHIBIT_PACKAGE_STRIP = "0"
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INSANE_SKIP = "ldflags"

do_image[nostamp] = "1"

# Only build the initramfs
python __anonymous() {
    d.setVar('INITRAMFS_IMAGE', d.getVar('PN'))
    d.setVar('INITRAMFS_IMAGE_BUNDLE', '0')
}

cleanup_root_files () {
    rm -rf ${IMAGE_ROOTFS}/media
    rm -rf ${IMAGE_ROOTFS}/mnt
    rm -rf ${IMAGE_ROOTFS}/srv
    rm -rf ${IMAGE_ROOTFS}/boot/*
}

create_sysroot_dir() {
    mkdir -p ${IMAGE_ROOTFS}/sysroot
}

IMAGE_PREPROCESS_COMMAND += "create_sysroot_dir;"
ROOTFS_POSTPROCESS_COMMAND += "cleanup_root_files;"
