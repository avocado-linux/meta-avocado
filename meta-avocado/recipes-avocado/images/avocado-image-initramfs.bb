DESCRIPTION = "Avocado initramfs image"
LICENSE = "Apache-2.0"

inherit image

PACKAGE_ARCH = "${MACHINE_ARCH}"
IMAGE_LINK_NAME = ""
IMAGE_NAME_SUFFIX ?= ""
IMAGE_MACHINE_SUFFIX = "-${MACHINE_SHORT_NAME}"
export IMAGE_BASENAME = "${MLPREFIX}avocado-image-initramfs"
IMAGE_NAME = "${IMAGE_BASENAME}${IMAGE_MACHINE_SUFFIX}"
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

create_dirs() {
    mkdir -p ${IMAGE_ROOTFS}/sysroot
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
IMAGE_PREPROCESS_COMMAND += "create_dirs; cleanup_users;"
ROOTFS_POSTPROCESS_COMMAND += "cleanup_root_files;"
