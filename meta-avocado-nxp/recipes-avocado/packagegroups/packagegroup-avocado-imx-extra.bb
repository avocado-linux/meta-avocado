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

# imx93-frdm names no firmware here. The 88W8997 packages this variable lists
# are unreachable at the 6.18 BSP, and the part NXP replaced them with already
# arrives without this packagegroup's help.
#
# NXP moved the SoC off the 8997. meta-imx layer.conf:172 removes the
# mrvl8997 / nxp8997-pcie / nxp8997-sdio machine features and :277 adds
# nxpaw693-sdio for mx93-nxp-bsp, which covers FRDM and not just the EVKs. Its
# firmware-nxp-wifi bbappend then drops meta-freescale's surviving 8997
# package:
#
#   #-----------------don't upstream, keep in imx ------------------------
#   PACKAGES:remove = " ${PN}-nxp8997-sdio "
#
# That same bbappend packages the replacement - ${PN}-nxpaw693-sdio, carrying
# sdiw693_wlan_v1.bin.se, sduartiw693_combo_v1.bin.se and
# uartiw693_bt_v1.bin.se - and layer.conf:116 puts it in MACHINE_FIRMWARE,
# which imx-base.inc:453 folds into MACHINE_EXTRA_RRECOMMENDS. The AW693
# firmware therefore follows its machine feature on its own; naming it here
# would duplicate a BSP decision, and naming any 8997 package would fail the
# taskgraph.
#
# oe-core's linux-firmware does not substitute for the 8997 either. Its
# -nxp8997-pcie and -nxp8997-sdio are ALLOW_EMPTY shims carrying no FILES, and
# the only reachable content behind them is -nxp8997-common's two Bluetooth
# files (uartuart8997_bt_v4.bin, helper_uart_3000000.bin). The blob the driver
# loads, mrvl/sdiouart8997_combo_v4.bin, is packaged only by meta-freescale, in
# the package meta-imx removes above - so pulling the shims in would install
# two Bluetooth files and read like WiFi coverage that is not there.
#
# Which part to target is moot until a module is fitted: this unit's M.2 slot
# is empty, and the FRDM-IMX93's supported module is an 88W8987, a third answer
# again.
NXP_WIFI_FIRMWARE:avocado-imx93-frdm = ""

RDEPENDS:${PN} = " \
  ${NXP_WIFI_DRIVER} \
  ${NXP_WIFI_FIRMWARE} \
  kernel-modules \
"
