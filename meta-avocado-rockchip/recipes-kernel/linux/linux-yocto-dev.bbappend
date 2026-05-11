FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

# Pin away from linux-yocto-dev's AUTOREV (tracks Linus master tip and
# frequently breaks -- last hit: modpost EXPORT_SYMBOL conflict on
# security_path_rmdir at v6.9 HEAD, 2024-05). v6.12 is a Linux LTS kernel,
# has rk3588-orangepi-5-plus.dts (added in v6.7), and YP's
# v6.12/standard/base branch carries the matching kernel-cache integration.
#
# When the meta-rockchip layer's own linux-yocto-dev support catches up
# (e.g. via a future meta-rockchip release that pins SRCREVs themselves),
# this block becomes unnecessary and can be deleted.
KBRANCH         = "v6.12/standard/base"
LINUX_VERSION   = "6.12"
SRCREV_machine  = "24aa244d67f02e2709e9e9f0365f2b41db0386c5"
SRCREV_meta     = "89cdc6b11d8516512a1e7b584bbe19900a55059b"

# Override SRC_URI to switch the yocto-kernel-cache branch to yocto-6.12 --
# the base recipe hardcodes branch=master which doesn't carry the v6.12 .scc
# files at the SRCREV_meta SHA above. Re-declare both fetcher entries so the
# kmeta branch can change.
SRC_URI = "git://git.yoctoproject.org/linux-yocto-dev.git;branch=${KBRANCH};name=machine;protocol=https \
           git://git.yoctoproject.org/yocto-kernel-cache;type=kmeta;name=meta;branch=yocto-6.12;destsuffix=${KMETA};protocol=https"

# Same fragments as linux-yocto. Upstream meta-rockchip ships its own
# linux-yocto-dev.bbappend that adds COMPATIBLE_MACHINE:orangepi-5-plus
# and the rockchip-kmeta kmeta SRC_URI; our bbappend stacks on top.
SRC_URI:append:rk3588 = " \
    file://avocado-core.cfg \
    file://avocado-extra.cfg \
    file://avocado-rk3588.cfg \
"

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
