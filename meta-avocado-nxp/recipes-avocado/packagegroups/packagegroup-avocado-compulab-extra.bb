DESCRIPTION = "Packagegroup for extra packages in Avocado CompuLab i.MX builds"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

# CompuLab SOM/gateway WiFi+BT: Intel AX200/AX210 (iwlwifi) and Marvell are
# delivered as firmware via MACHINE_FIRMWARE in compulab-imx8mp.inc. Unlike the
# NXP EVK there is no out-of-tree wlan driver. `kernel-modules` publishes every
# module the kernel builds as =m to the feed; we deliberately do NOT hard-list
# kernel-module-iwlwifi / -btusb here because if linux-compulab's defconfig
# builds them =y the package won't exist and the rootfs build fails. Pin
# specific kernel-module-* in the BSP extension once the lsmod set is known.
RDEPENDS:${PN} = " \
  kernel-modules \
  wireless-regdb-static \
  avocado-devicetree \
"
