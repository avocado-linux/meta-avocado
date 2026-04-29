DESCRIPTION = "Packagegroup for extra packages in Avocado NXP i.MX builds"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup nospdx
PACKAGES = "${PN}"

# NXP 88W8997 WiFi driver (out-of-tree mwifiex fork)
NXP_WIFI_DRIVER = " \
  kernel-module-nxp-wlan \
"

# NXP 88W8997 WiFi + BT firmware
NXP_WIFI_FIRMWARE = " \
  firmware-nxp-wifi-nxp8997-sdio \
  firmware-nxp-wifi-nxp8997-pcie \
"

RDEPENDS:${PN} = " \
  ${NXP_WIFI_DRIVER} \
  ${NXP_WIFI_FIRMWARE} \
  kernel-modules \
"
