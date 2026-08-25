DESCRIPTION = "Packagegroup for extra packages in Avocado Variscite i.MX builds"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

# Variscite DART-MX8M-PLUS WiFi/BT: the NXP IW612 (Wi-Fi 6 + BT/802.15.4) over
# SDIO, enabled by the nxpiw612-sdio MACHINE_FEATURE in the vendor machine conf;
# variscite.inc pulls iw612-utils and the firmware ships via MACHINE_FIRMWARE.
# Unlike the NXP EVK there is no out-of-tree 88W8997 wlan driver here.
# `kernel-modules` publishes every module the kernel builds as =m to the feed;
# we deliberately do NOT hard-list specific kernel-module-* names because if the
# defconfig builds one =y the package won't exist and the rootfs build fails.
# Pin the specific kernel-module-* in the BSP extension once the booted lsmod
# set is known.
RDEPENDS:${PN} = " \
  kernel-modules \
  wireless-regdb-static \
  avocado-devicetree \
"
