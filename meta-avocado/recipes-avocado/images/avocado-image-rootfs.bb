DESCRIPTION = "Avocado image rootfs"
LICENSE = "Apache-2.0"

inherit image

IMAGE_FSTYPES = "${ROOT_FSTYPES}"
SQUASHFS_COMPRESSION = "zstd"
SQUASHFS_COMPRESSION_LEVEL = "1"
WIC_CREATE_EXTRA_ARGS = "--no-fstab-update"
WIC_ROOTFS_FORMAT = "squashfs"

IMAGE_FEATURES += "read-only-rootfs"
ROOTFS_IMAGE_EXTRA_INSTALL ??= ""
IMAGE_INSTALL = "packagegroup-avocado-rootfs ${ROOTFS_IMAGE_EXTRA_INSTALL}"
DISTRO_FEATURES_BACKFILL_CONSIDERED=""

cleanup_root_files () {
    rm -rf ${IMAGE_ROOTFS}/media
    rm -rf ${IMAGE_ROOTFS}/mnt
    rm -rf ${IMAGE_ROOTFS}/srv
    rm -rf ${IMAGE_ROOTFS}/boot/*
    rm -rf ${IMAGE_ROOTFS}/usr/lib/opkg
}

ROOTFS_POSTPROCESS_COMMAND += "cleanup_root_files;"
