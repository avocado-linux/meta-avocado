DESCRIPTION = "Avocado image rootfs"
LICENSE = "Apache-2.0"

PV = "${DISTRO_VERSION}"

inherit image
IMGCLASSES += " image-os"
inherit_defer ${IMGCLASSES}

IMAGE_LINK_NAME = ""
IMAGE_MACHINE_SUFFIX = "-${MACHINE_SHORT_NAME}"
IMAGE_NAME = "${IMAGE_BASENAME}${IMAGE_MACHINE_SUFFIX}"
IMAGE_NAME_SUFFIX = ""
IMAGE_FSTYPES = "${ROOT_FSTYPES}"
WIC_CREATE_EXTRA_ARGS = "--no-fstab-update"
WIC_ROOTFS_FORMAT = "erofs-lz4"

IMAGE_FEATURES += "read-only-rootfs"
IMAGE_INSTALL = "packagegroup-avocado-rootfs ${ROOTFS_IMAGE_EXTRA_INSTALL}"
DISTRO_FEATURES_OPTED_OUT = ""

cleanup_root_files () {
    rm -rf ${IMAGE_ROOTFS}/media
    rm -rf ${IMAGE_ROOTFS}/mnt
    rm -rf ${IMAGE_ROOTFS}/srv
    rm -rf ${IMAGE_ROOTFS}/boot/*
}

create_dirs() {
    mkdir -p ${IMAGE_ROOTFS}/opt
}

IMAGE_PREPROCESS_COMMAND += "create_dirs;"
ROOTFS_POSTPROCESS_COMMAND += "cleanup_root_files;"

# avocado_security_capabilities_write_artifact is provided by
# avocado-security-capabilities.bbclass (globally inherited via
# conf/distro/include/avocado-security.inc); it writes
# /etc/avocado-security-capabilities from this machine's
# AVOCADO_SECURITY_CAPABILITIES so an on-device extension can check
# eligibility without a build-time BitBake channel.
ROOTFS_POSTPROCESS_COMMAND += "avocado_security_capabilities_write_artifact;"

# The artifact's CONTENT comes from AVOCADO_SECURITY_CAPABILITIES, so the task
# that writes it has to depend on that variable or editing a machine's
# declaration leaves do_rootfs looking unchanged: it is not rerun, do_image
# packages the cached rootfs, and the image ships the previous declaration with
# nothing reporting it. A vardeps flag on the function itself does NOT achieve
# this - measured, not assumed - because the function is only ever named from
# ROOTFS_POSTPROCESS_COMMAND rather than called by the task, so its flags never
# reach do_rootfs's signature. The dependency has to sit on the task.
do_rootfs[vardeps] += "AVOCADO_SECURITY_CAPABILITIES"
