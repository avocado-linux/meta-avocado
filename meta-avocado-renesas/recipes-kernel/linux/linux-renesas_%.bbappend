FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = " file://avocado-core.cfg \
        file://avocado-extra.cfg \
        file://panfrost.cfg \
        file://0001-dts-renesas-enable-mali-gpu.patch \
        file://0002-dts-renesas-add-fixed-gpu-regulator.patch"

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
