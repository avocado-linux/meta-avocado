FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

# Same fragments as linux-yocto. Upstream meta-rockchip ships its own
# linux-yocto-dev.bbappend that adds COMPATIBLE_MACHINE:orangepi-5-plus
# and the rockchip-kmeta kmeta SRC_URI; our bbappend stacks on top.
SRC_URI:append:rk3588 = " \
    file://avocado-core.cfg \
    file://avocado-extra.cfg \
    file://avocado-rk3588.cfg \
"

inherit avocado-kernel-feed
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
