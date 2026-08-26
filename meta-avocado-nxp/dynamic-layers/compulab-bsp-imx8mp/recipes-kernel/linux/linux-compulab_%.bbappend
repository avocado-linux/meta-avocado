# Kernel config fragments + the HDMI dts live in the in-tree linux files dir
# (shared with linux-imx); this bbappend sits under dynamic-layers/ so point at
# it via the layer.conf var rather than ${THISDIR}/files.
FILESEXTRAPATHS:prepend := "${AVOCADO_NXP_KERNEL_FILESDIR}:"

SRC_URI += " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
  file://avocado-wireless.cfg \
  file://avocado-netfilter.cfg \
  file://avocado-usb-serial.cfg \
  file://avocado-compulab.cfg \
  file://ucm-imx8m-plus-hdmi.dts \
"

# Drop our HDMI-only board variant into the CompuLab dts dir so KERNEL_DEVICETREE
# can build compulab/ucm-imx8m-plus-hdmi.dtb. It #includes the stock CompuLab
# fragments (som/mmc/pcie/sb-carrier/hdmi), so it must live alongside them.
# Avoids editing the vendor base dts (which enables unwired MIPI+LVDS and blocks
# the imx-drm KMS aggregate -- see the .dts header).
do_configure:prepend() {
  install -m 0644 ${UNPACKDIR}/ucm-imx8m-plus-hdmi.dts \
    ${S}/arch/arm64/boot/dts/compulab/ucm-imx8m-plus-hdmi.dts
}

do_configure:append() {
  cat ${UNPACKDIR}/*.cfg >> ${B}/.config
}

# CompuLab's recipe sets KERNEL_SPLIT_MODULES = "0", lumping every module into
# one kernel-modules package -- so no individual kernel-module-* packages enter
# the feed. The Avocado feed model (and avocado-kernel-feed / -builtin-provides)
# require per-module packaging, e.g. packagegroup-avocado-initramfs-modules
# pulls kernel-module-zram-${KERNEL_VERSION}. Re-enable the split (OE default).
KERNEL_SPLIT_MODULES = "1"

# dm-crypt/dm-verity capability, unconditional - see avocado-security-kernel.inc
# for why capability is never gated on a DISTRO_FEATURE. The fragments land in
# UNPACKDIR and are merged by the `cat ${UNPACKDIR}/*.cfg` in do_configure:append
# below, same as every other fragment this bbappend carries.
require recipes-kernel/linux/avocado-security-kernel.inc

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
