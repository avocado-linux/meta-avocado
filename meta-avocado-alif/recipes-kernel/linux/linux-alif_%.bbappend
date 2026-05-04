FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append:devkit-e8 = " \
    file://avocado-core.cfg \
    file://avocado-extra.cfg \
    file://avocado-sd-rootfs.cfg \
    file://avocado-cmdline.cfg \
"

inherit avocado-kernel-feed
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
