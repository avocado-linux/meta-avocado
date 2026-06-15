FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
  file://avocado-wireless.cfg \
  file://avocado-netfilter.cfg \
  file://avocado-usb-serial.cfg \
  file://avocado-variscite.cfg \
"

# linux-variscite-imx is linux-imx-based (KBUILD_DEFCONFIG = imx8_var_defconfig,
# an in-tree defconfig), not kernel-yocto/.scc -- so merge the avocado fragments
# by appending to the assembled .config, last wins (same as linux-compulab /
# linux-imx).
do_configure:append() {
  cat ${WORKDIR}/*.cfg >> ${B}/.config
}

# NXP's linux-imx defconfig lumps every module into one kernel-modules package
# (KERNEL_SPLIT_MODULES = "0"), so no individual kernel-module-* packages enter
# the feed. The Avocado feed model (avocado-kernel-feed / -builtin-provides and
# packagegroup-avocado-{rootfs,initramfs}-modules) requires per-module packaging.
# Re-enable the split (OE default).
KERNEL_SPLIT_MODULES = "1"

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
