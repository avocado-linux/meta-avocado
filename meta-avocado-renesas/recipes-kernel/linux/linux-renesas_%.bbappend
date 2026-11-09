FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = " file://avocado-core.cfg \
        file://avocado-extra.cfg \
        file://panfrost.cfg \
        file://0001-dts-renesas-enable-mali-gpu.patch \
        file://0002-dts-renesas-add-fixed-gpu-regulator.patch"

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc

# Patches that target Renesas's own kernel and EVK, not SolidRun's fork:
# - meta-rz-bsp's "reference only" RZ/G3E SMARC LVDS / IT6263 display set
#   (added to every 6.1 kernel in 2026-08; fails on renesas-smarc2 dtsi).
# - meta-rz-drpai V1.50's devicetree patch, renamed from the name
#   meta-rzv2n removes (it applies its own -solidrun copy instead), and
#   its eMMC_SD_SEL patch for r9a09g056n48-rzv2n-evk.dts.
SRC_URI:remove:rzv2n-sr-som = " \
    file://v6.1/display/0001-drm-bridge-adv7511-Clear-HPD-IRQ-before-powering-on-.patch \
    file://v6.1/display/0002-gpu-drm-bridge-Add-ITE-it6263-LVDS-to-HDMI-bridge-dr.patch \
    file://v6.1/display/0003-arm64-defconfig-enable-LVDS-and-IT6263-LVSD-to-HDMI-.patch \
    file://v6.1/display/0004-arm64-dts-renesas-rzg3e-smarc-lvds-add-macro-to-sele.patch \
    file://v6.1/display/0005-arm64-dts-renesas-r9a09g047e57-smarc-enable-LVDS-sup.patch \
    file://v6.1/display/0006-gpu-drm-bridge-Support-S2R-ITE-it6263.patch \
    file://v6.1/display/0007-drm-bridge-ite-it6263-Support-VESA-24-input-format.patch \
    file://0001-add-drpai-property-to-devicetree-RZV2N.patch \
    file://0003-config-macro-eMMC_SD_SEL-to-support-eMMC-boot-RZV2N.patch \
"
