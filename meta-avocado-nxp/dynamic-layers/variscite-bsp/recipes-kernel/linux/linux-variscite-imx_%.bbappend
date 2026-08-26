# Kernel config fragments are shared with the in-tree linux-imx bbappend; see
# AVOCADO_NXP_KERNEL_FILESDIR in conf/layer.conf.
FILESEXTRAPATHS:prepend := "${AVOCADO_NXP_KERNEL_FILESDIR}:"

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
  cat ${UNPACKDIR}/*.cfg >> ${B}/.config
}

# NXP's linux-imx defconfig lumps every module into one kernel-modules package
# (KERNEL_SPLIT_MODULES = "0"), so no individual kernel-module-* packages enter
# the feed. The Avocado feed model (avocado-kernel-feed / -builtin-provides and
# packagegroup-avocado-{rootfs,initramfs}-modules) requires per-module packaging.
# Re-enable the split (OE default).
KERNEL_SPLIT_MODULES = "1"

# dm-crypt/dm-verity capability, unconditional - see avocado-security-kernel.inc
# for why capability is never gated on a DISTRO_FEATURE. The fragments land in
# UNPACKDIR and are merged by the `cat ${UNPACKDIR}/*.cfg` in do_configure:append
# below, same as every other fragment this bbappend carries.
require recipes-kernel/linux/avocado-security-kernel.inc

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
