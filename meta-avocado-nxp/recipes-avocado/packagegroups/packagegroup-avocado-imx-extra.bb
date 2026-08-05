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
#
# -nxp8997-pcie is deliberately not named. wrynose meta-freescale's
# firmware-nxp-wifi_1.1.bb PACKAGES block ships -nxp8997-sdio and
# -nxpaw693-pcie but no -nxp8997-pcie, so depending on it aborts the taskgraph
# with "Nothing RPROVIDES". The master commit this layer set pinned before the
# wrynose bump did package it.
#
# imx93-evk is the only machine that reaches that error. imx8mp-evk, imx91-frdm
# and imx95-frdm stop earlier on layer compat - their meta-imx pin declares
# LAYERSERIES_COMPAT_fsl-bsp-release = "mickledore nanbield scarthgap" - and
# avocado-ucm-imx8m-plus.conf drops this packagegroup outright.
NXP_WIFI_FIRMWARE = " \
  firmware-nxp-wifi-nxp8997-sdio \
"

# imx93-frdm ships no 88W8997 firmware, because at the 6.18 BSP none is
# reachable from any layer in this set.
#
# NXP moved the SoC off the part. meta-imx layer.conf:172 removes the
# mrvl8997 / nxp8997-pcie / nxp8997-sdio machine features and :277 adds
# nxpaw693-sdio for mx93-nxp-bsp, which covers FRDM and not just the EVKs. Its
# firmware-nxp-wifi bbappend then drops meta-freescale's surviving package:
#
#   #-----------------don't upstream, keep in imx ------------------------
#   PACKAGES:remove = " ${PN}-nxp8997-sdio "
#
# and the replacement that machine feature names resolves to nothing either -
# meta-freescale packages -nxpaw693-pcie, not -nxpaw693-sdio.
#
# oe-core's linux-firmware does not substitute. Its -nxp8997-pcie and
# -nxp8997-sdio are ALLOW_EMPTY shims carrying no FILES, and the only reachable
# content behind them is -nxp8997-common's two Bluetooth files
# (uartuart8997_bt_v4.bin, helper_uart_3000000.bin). The blob the driver loads,
# mrvl/sdiouart8997_combo_v4.bin, is packaged only by meta-freescale, in the
# package meta-imx removes above.
#
# An empty set states that accurately; pulling the linux-firmware shims would
# install two Bluetooth files and read like WiFi coverage that is not there.
# Revisit once a board with a module fitted can say which part to target - this
# unit's M.2 slot is empty, and the FRDM-IMX93's supported module is an 88W8987,
# which is a third answer again.
NXP_WIFI_FIRMWARE:avocado-imx93-frdm = ""

RDEPENDS:${PN} = " \
  ${NXP_WIFI_DRIVER} \
  ${NXP_WIFI_FIRMWARE} \
  kernel-modules \
"
