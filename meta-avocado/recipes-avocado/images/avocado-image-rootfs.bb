DESCRIPTION = "Avocado image rootfs"
LICENSE = "Apache-2.0"

inherit image
IMAGE_LINK_NAME = ""
IMAGE_MACHINE_SUFFIX = "-${MACHINE_SHORT_NAME}"
IMAGE_NAME = "${IMAGE_BASENAME}${IMAGE_MACHINE_SUFFIX}"
IMAGE_NAME_SUFFIX = ""
IMAGE_FSTYPES = "${ROOT_FSTYPES}"
SQUASHFS_COMPRESSION = "zstd"
SQUASHFS_COMPRESSION_LEVEL = "1"
WIC_CREATE_EXTRA_ARGS = "--no-fstab-update"
WIC_ROOTFS_FORMAT = "squashfs"

IMAGE_FEATURES += "read-only-rootfs"
IMAGE_INSTALL = "packagegroup-avocado-rootfs ${ROOTFS_IMAGE_EXTRA_INSTALL}"
DISTRO_FEATURES_BACKFILL_CONSIDERED=""

cleanup_root_files () {
    rm -rf ${IMAGE_ROOTFS}/media
    rm -rf ${IMAGE_ROOTFS}/mnt
    rm -rf ${IMAGE_ROOTFS}/srv
    rm -rf ${IMAGE_ROOTFS}/boot/*
}

create_dirs() {
    mkdir -p ${IMAGE_ROOTFS}/opt
}

cleanup_users() {
    # Filter passwd file - keep only systemd*, root, nobody, messagebus
    if [ -f ${IMAGE_ROOTFS}/etc/passwd ]; then
        grep -E "^(systemd|root|nobody|messagebus)" ${IMAGE_ROOTFS}/etc/passwd > ${IMAGE_ROOTFS}/etc/passwd.tmp || true
        mv ${IMAGE_ROOTFS}/etc/passwd.tmp ${IMAGE_ROOTFS}/etc/passwd
    fi

    # Filter shadow file - keep only systemd*, root, nobody, messagebus
    if [ -f ${IMAGE_ROOTFS}/etc/shadow ]; then
        grep -E "^(systemd|root|nobody|messagebus)" ${IMAGE_ROOTFS}/etc/shadow > ${IMAGE_ROOTFS}/etc/shadow.tmp || true
        mv ${IMAGE_ROOTFS}/etc/shadow.tmp ${IMAGE_ROOTFS}/etc/shadow
    fi

    # Filter group file - keep only systemd*, root, nobody, messagebus
    if [ -f ${IMAGE_ROOTFS}/etc/group ]; then
        grep -E "^(systemd|root|nobody|messagebus)" ${IMAGE_ROOTFS}/etc/group > ${IMAGE_ROOTFS}/etc/group.tmp || true
        mv ${IMAGE_ROOTFS}/etc/group.tmp ${IMAGE_ROOTFS}/etc/group
    fi

    # Filter gshadow file - keep only systemd*, root, nobody, messagebus
    if [ -f ${IMAGE_ROOTFS}/etc/gshadow ]; then
        grep -E "^(systemd|root|nobody|messagebus)" ${IMAGE_ROOTFS}/etc/gshadow > ${IMAGE_ROOTFS}/etc/gshadow.tmp || true
        mv ${IMAGE_ROOTFS}/etc/gshadow.tmp ${IMAGE_ROOTFS}/etc/gshadow
    fi
}
IMAGE_PREPROCESS_COMMAND += "create_dirs;"
ROOTFS_POSTPROCESS_COMMAND += "cleanup_root_files;"
