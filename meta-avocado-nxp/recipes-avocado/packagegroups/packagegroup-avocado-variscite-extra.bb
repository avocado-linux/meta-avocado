DESCRIPTION = "Packagegroup for extra packages in Avocado Variscite i.MX builds"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

# Variscite DART WiFi/BT (i.MX8M Plus and i.MX95): the NXP IW612 (Wi-Fi 6 +
# BT/802.15.4) over SDIO, enabled by the nxpiw612-sdio MACHINE_FEATURE in the
# vendor machine conf; variscite.inc pulls iw612-utils and the firmware ships
# via MACHINE_FIRMWARE.
#
# The IW612 *does* need NXP's out-of-tree wlan driver (moal/mlan) -- an earlier
# comment here claimed it did not, which was wrong: there is no in-tree
# nxpwifi/mwifiex module for this part in 6.18, meta-variscite-bsp-imx carries a
# kernel-module-nxp-wlan bbappend precisely to control how moal is loaded
# (var_wifi_mod_para.conf), and moal+mlan are the loaded modules on Variscite's
# own reference image. Removing packagegroup-avocado-imx-extra (see
# avocado-variscite.inc) drops the only thing that pulled that recipe, so name
# it here, or the firmware ships with no driver to use it and WiFi is silently
# dead. BT over UART (btnxpuart) is in-tree and unaffected.
# `kernel-modules` publishes every module the kernel builds as =m to the feed;
# we deliberately do NOT hard-list specific kernel-module-* names because if the
# defconfig builds one =y the package won't exist and the rootfs build fails.
# Pin the specific kernel-module-* in the BSP extension once the booted lsmod
# set is known.
RDEPENDS:${PN} = " \
  kernel-modules \
  kernel-module-nxp-wlan \
  wireless-regdb-static \
  avocado-devicetree \
"
