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

# Keep the SSH host identity across reboots.
#
# oe-core's read_only_rootfs_hook finds no pre-generated key in /etc/ssh and
# concludes the device cannot keep one, so it writes /etc/default/ssh pointing
# sshd at sshd_config_readonly with keys under /var/run/ssh - tmpfs. The device
# then presents a NEW host key on every boot: every client's known_hosts breaks
# on every reboot, and `avocado container dev up`, which bootstraps the device
# over SSH, cannot reconnect to a device that has rebooted.
#
# The inference is sound for a stateless image and wrong for this one. The rootfs
# is read-only but /var is writable and persistent, which is the third case
# oe-core does not model - its choice is between shipping a key in the image
# (which we will not do) and having no key survive. The shipped sshd_config
# already points HostKey at /var/lib/ssh, so only the override needs undoing.
#
# Appending is enough rather than patching: sshd_check_keys sources this file as
# shell, so the last assignment wins, and its generate_key does mkdir -p on the
# key directory. Keys are generated once into /var/lib/ssh on first boot and
# reused after.
#
# This runs from IMAGE_PREPROCESS_COMMAND, not ROOTFS_POSTPROCESS_COMMAND, and
# the distinction is load-bearing. A recipe-level `ROOTFS_POSTPROCESS_COMMAND +=`
# does NOT order after the entry rootfs-postcommands.bbclass adds: measured on
# this image, read_only_rootfs_hook runs last of the three. Placed there, this
# function ran before oe-core had created /etc/default/ssh at all, the guard
# below skipped, and the volatile values were written afterwards - a silent
# no-op that looked like a working patch. IMAGE_PREPROCESS_COMMAND runs after
# do_rootfs finishes and before the erofs image is made, so the file is present
# and nothing appends after us.
persist_ssh_host_keys () {
    if [ -f ${IMAGE_ROOTFS}${sysconfdir}/default/ssh ]; then
        printf 'SYSCONFDIR=/var/lib/ssh\nSSHD_OPTS=\n' \
            >> ${IMAGE_ROOTFS}${sysconfdir}/default/ssh
    fi
}

IMAGE_PREPROCESS_COMMAND += "create_dirs;"
IMAGE_PREPROCESS_COMMAND += "persist_ssh_host_keys;"
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
