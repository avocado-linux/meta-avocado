FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

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
  install -m 0644 ${WORKDIR}/ucm-imx8m-plus-hdmi.dts \
    ${S}/arch/arm64/boot/dts/compulab/ucm-imx8m-plus-hdmi.dts
}

do_configure:append() {
  cat ${WORKDIR}/*.cfg >> ${B}/.config
}

# CompuLab's recipe sets KERNEL_SPLIT_MODULES = "0", lumping every module into
# one kernel-modules package -- so no individual kernel-module-* packages enter
# the feed. The Avocado feed model (and avocado-kernel-feed / -builtin-provides)
# require per-module packaging, e.g. packagegroup-avocado-initramfs-modules
# pulls kernel-module-zram-${KERNEL_VERSION}. Re-enable the split (OE default).
KERNEL_SPLIT_MODULES = "1"

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
