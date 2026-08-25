DESCRIPTION = "Packagegroup for extra packages in Avocado NXP i.MX builds"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup nospdx
PACKAGES = "${PN}"

# NXP WiFi driver: kernel-module-nxp-wlan is the same out-of-tree module for
# every NXP WiFi chip meta-imx-bsp knows about, 88W8997 included. Kept as a
# firm RDEPENDS rather than left to meta-imx-bsp/conf/layer.conf:110's own
# MACHINE_EXTRA_RRECOMMENDS (which already adds it for mx93-nxp-bsp once
# nxpaw693-sdio lands in MACHINE_FEATURES, layer.conf:277) so the module is
# guaranteed present - not merely recommended - the day a WiFi module is
# fitted to this unit's empty M.2 slot, independent of NO_RECOMMENDATIONS
# policy on any given image.
NXP_WIFI_DRIVER = " \
  kernel-module-nxp-wlan \
"

# NXP WiFi firmware: whatever the machine's own MACHINE_FEATURES select.
# meta-freescale imx-base.inc and meta-imx-bsp layer.conf translate the
# nxpwifi-all-{sdio,pcie,usb} / nxpaw693-* / nxpiw612-sdio features into
# firmware-nxp-wifi-* package names in MACHINE_FIRMWARE, and keep those names
# in step with what firmware-nxp-wifi actually packages at each release (the
# 88W8997 package this group used to name by hand is removed by meta-imx from
# 6.18 on). Same firm-RDEPENDS reasoning as the driver above: MACHINE_FIRMWARE
# only reaches the image as a recommendation otherwise.
NXP_WIFI_FIRMWARE = "${MACHINE_FIRMWARE}"
# The 8M Plus EVK's stock M.2 module is an 88W8997, which NXP's 6.18 firmware
# and moal driver no longer cover; firmware-nxp-wifi-8997 carries the blobs for
# the mainline mwifiex/btnxpuart path (see that recipe and the EVK's
# mwifiex.cfg kernel fragment). Feed-only here; the BSP extension installs it.
NXP_WIFI_FIRMWARE:append:avocado-imx8mp-evk = " firmware-nxp-wifi-8997"

RDEPENDS:${PN} = " \
  ${NXP_WIFI_DRIVER} \
  ${NXP_WIFI_FIRMWARE} \
  kernel-modules \
"
