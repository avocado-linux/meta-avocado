FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
FILESEXTRAPATHS:prepend:imx95-frdm := "${THISDIR}/files/imx95-frdm:"

SRCREV:avocado-imx95-frdm = "5a0a5e71d2bd130577c7330cbb3764c68ebcb3dc"
LINUX_VERSION:avocado-imx95-frdm = "6.6.52"

# The patches from meta-imx-frdm target older kernels and do not apply to the
# version pinned above. Strip them all for this machine.
SRC_URI:remove:avocado-imx95-frdm = " \
  file://0001-gpio-pca953x-fix-pca953x_irq_bus_sync_unlock-race.patch \
  file://0002-arm64-dts-add-i.MX93-11x11-FRDM-basic-support.patch \
  file://0003-arm64-dts-add-imx93-11x11-frdm-mt9m114-dts.patch \
  file://0004-Add-DSI-Panel-for-imx93.patch \
  file://0005-Add-CTP-support-for-waveshare-panel.patch \
  file://0006-arm64-dts-add-imx93-11x11-frdm-tianma-wvga-panel-dts.patch \
  file://0007-arm64-dts-add-imx93-11x11-frdm-aud-hat-dts.patch \
  file://0008-arm64-dts-add-button-support.patch \
  file://0009-arm64-dts-add-imx93-11x11-frdm-ov5640-dts.patch \
  file://0010-arm64-dts-add-imx93-11x11-frdm-ld.dts-for-lpm.patch \
  file://0011-arm64-dts-add-pwm-function-of-the-LED.patch \
  file://0012-arm64-dts-add-imx93-11x11-frdm-8mic.dts.patch \
  file://0013-arm64-dts-add-imx93-11x11-frdm-lpuart.dts.patch \
  file://0014-arm64-dts-add-imx91-frdm-dts-files.patch \
  file://0015-arm64-dts-add-imx91-11x11-frdm-tianma-wvga-panel-dts.patch \
  file://0016-arm64-dts-add-imx91-11x11-frdm-mt9m114.dts.patch \
  file://0017-arm64-dts-add-imx91-11x11-frdm-aud-hat-dts.patch \
  file://0018-arm64-dts-add-imx91-11x11-frdm-8mic.dts-and-fix-imx9.patch \
  file://0019-arm64-dts-add-imx91-11x11-frdm-lpuart.dts.patch \
  file://0020-LF-13459-clk-imx-Fix-the-pll-power-up-flow.patch \
  file://0021-thermal-imx91-bug-fix-Temperature-read-returns-Resou.patch \
  file://0022-LF-14498-arm64-dts-imx91-Correct-ENET1_TD3-and-I2C2_.patch \
  file://0023-arm64-dts-Add-i.MX8MP-FRDM-board-support.patch \
  file://0024-arm64-dts-add-os08a20-device-node-for-i.MX8MP-FRDM-b.patch \
  file://0025-arm64-dts-add-dual-BOE-EV121WXM-N10-1850-LVDS-panel-.patch \
  file://0026-arm64-dts-imx8mp-frdm-add-dual-os08a20-sensors-for-i.patch \
  file://0027-arm64-dts-imx8mp-frdm-add-AP1302-support.patch \
  file://0028-arm64-dts-imx8mp-frdm-add-dual-AP1302-support.patch \
  file://0029-arm64-dts-imx8mp-frdm-add-imx8mp-frdm-8mic.dts.patch \
  file://0030-arm64-dts-imx8mp-frdm-enable-7inch-waveshare-panel.patch \
  file://0031-arm64-dts-imx8mp-frdm-add-imx8mp-frdm-rpmsg.dts.patch \
  file://0032-arm64-dts-imx8mp-frdm-using-green-led-instead-of-blu.patch \
  file://0033-arm64-dts-imx8mp-frdm-fix-wifi-reset-pin.patch \
  file://0034-arm64-dts-imx8mp-frdm-clean-imx8mp-frdm.dts.patch \
  file://0035-arm64-dts-imx8mp-frdm-fix-interrupt-pin-in-imx8mp-fr.patch \
  file://0036-Revert-commit-e85faa36ec41d8304a4f0123d6152274595f1e.patch \
  file://0037-arm64-dts-imx8mp-frdm-add-AP1302-support-instead-of-.patch \
  file://0038-arm64-dts-imx8mp-frdm-add-rpmsg-audio-support.patch \
  file://0039-drm-panel-panel-waveshare-dsi-Add-bridge-and-connect.patch \
  file://0040-arm64-dts-imx8mp-frdm-update-waveshare-panel-node.patch \
  file://0041-drm-panel-remove-wavesahre-node-in-simple-panel.patch \
  file://0042-arm64-dts-imx8mp-frdm-add-imx8mp-frdm-iw612-otbr-dts.patch \
  file://0043-arm64-dts-Add-dts-for-FRDM-IMX91S-board.patch \
  file://0044-arm64-dts-Add-imx91-11x11-frdm-imx91s-aud-hat-dts.patch \
  file://0045-arm64-dts-Add-imx91-11x11-frdm-imx91s-8mic.dts.patch \
  file://0046-arm64-dts-Add-imx91-11x11-frdm-imx91s-tianma-wvga-pa.patch \
  file://0047-arm64-dts-Add-imx91-11x11-frdm-imx91s-fec.dts.patch \
  file://0048-media-imx-parallel-Fix-OV5640-DVP-mode-capture-color.patch \
  file://0049-arm64-dts-Add-imx91-11x11-frdm-imx91s-mt9m114.dts.patch \
  file://0050-arm64-dts-Add-imx91-11x11-frdm-imx91s-ld.dts.patch \
  file://0051-arm64-dts-Add-imx91-11x11-frdm-imx91s-lpuart.dts.patch \
  file://0052-arm64-dts-Fix-connector-descriptions-in-FRDM-IMX-lpu.patch \
"

SRC_URI += " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
  file://avocado-wireless.cfg \
  file://avocado-netfilter.cfg \
  file://avocado-usb-serial.cfg \
"

SRC_URI:append:imx95-frdm = " \
  file://imx95-15x15-frdm.dts \
  file://imx95-15x15-frdm-boe-wxga-lvds-panel.dts \
  file://imx95-15x15-frdm-aud-hat.dts \
  file://imx95-15x15-frdm-8mic-reve.dts \
  file://imx95-15x15-frdm-waveshare-7inch-c-panel.dtso \
  file://imx95-15x15-frdm-os08a20.dtso \
  file://imx95-15x15-frdm-os08a20-combo.dtso \
  file://imx95-15x15-frdm-ap1302.dtso \
  file://imx95-frdm-dts-makefile.fragment \
"

KERNEL_DEVICETREE:append:imx95-frdm = " \
  freescale/imx95-15x15-frdm.dtb \
  freescale/imx95-15x15-frdm-boe-wxga-lvds-panel.dtb \
  freescale/imx95-15x15-frdm-aud-hat.dtb \
  freescale/imx95-15x15-frdm-8mic-reve.dtb \
  freescale/imx95-15x15-frdm-waveshare-7inch-c-panel.dtbo \
  freescale/imx95-15x15-frdm-os08a20.dtbo \
  freescale/imx95-15x15-frdm-os08a20-combo.dtbo \
  freescale/imx95-15x15-frdm-ap1302.dtbo \
"

SRC_URI:append:avocado-imx93-frdm = " \
  file://imx93-frdm/dm-crypt.cfg \
"

do_configure:append() {
  cat ${UNPACKDIR}/*.cfg >> ${B}/.config
  # UNPACKDIR, not WORKDIR: the stack was written against scarthgap, where
  # unpacked sources still landed in WORKDIR. Globbed there this matches nothing
  # and the fragments are dropped silently, leaving a kernel with no
  # CONFIG_DM_CRYPT and a /var that cannot be unlocked.
  for f in ${UNPACKDIR}/imx93-frdm/*.cfg; do
    [ -e "$f" ] && cat "$f" >> ${B}/.config
  done
}

do_configure:prepend:imx95-frdm() {
  destdir="${S}/arch/arm64/boot/dts/freescale"
  for f in imx95-15x15-frdm.dts \
            imx95-15x15-frdm-boe-wxga-lvds-panel.dts \
            imx95-15x15-frdm-aud-hat.dts \
            imx95-15x15-frdm-8mic-reve.dts \
            imx95-15x15-frdm-waveshare-7inch-c-panel.dtso \
            imx95-15x15-frdm-os08a20.dtso \
            imx95-15x15-frdm-os08a20-combo.dtso \
            imx95-15x15-frdm-ap1302.dtso; do
    cp "${WORKDIR}/${f}" "${destdir}/"
  done
  cat "${WORKDIR}/imx95-frdm-dts-makefile.fragment" >> "${destdir}/Makefile"
}

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
