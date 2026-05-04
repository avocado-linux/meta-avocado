FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

# Avocado config fragments. Upstream meta-rockchip's linux-yocto_%.bbappend
# already wires the rockchip-kmeta kmeta tree and per-machine COMPATIBLE_MACHINE
# (rock-5b is in scope; orangepi-5-plus uses linux-yocto-dev instead). Our
# fragments add what avocado needs on top: erofs/squashfs/zstd-RD,
# overlayfs, USB gadget configfs, etc.
SRC_URI:append:rk3588 = " \
    file://avocado-core.cfg \
    file://avocado-extra.cfg \
    file://avocado-rk3588.cfg \
"

# Boilerplate per distro/docs/adding-a-machine-target.md §10:
# adds the kernel to the avocado-cli kernel-resolver virtual, renames
# kernel-{devsrc,devicetree,modules} to include KERNEL_VERSION, emits
# per-kernel rootfs/initramfs module packagegroups. Additive in single-kernel
# feeds, load-bearing if/when an alt kernel is added later.
inherit avocado-kernel-feed
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
