FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = " file://avocado-core.cfg \
        file://avocado-extra.cfg \
        file://panfrost.cfg"

# These GPU-enablement patches target the SolidRun rzv2n dtsi
# (rzv2n-hummingboard-iiot-common.dtsi); only apply on that board so they do not
# break other Renesas machines that share this bbappend.
SRC_URI:append:rzv2n-sr-som = " file://0001-dts-renesas-enable-mali-gpu.patch \
        file://0002-dts-renesas-add-fixed-gpu-regulator.patch"

# TODO(gap-1/2): RZ/V2H RDK device tree. The vendor board dts exists -
# rzv2h-rdk-ver1.dts in Renesas-SST/linux-rz (branch ubuntu/rz-v2h-rdk, kernel
# 6.10) - so it is NOT authored from scratch; it is forward-ported onto
# linux-renesas 6.12 (rz-6.12-cip7) and wired into
# arch/arm64/boot/dts/renesas/Makefile so r9a09g057h44-rzv2h-rdk.dtb builds.
#
# Verified against rz-6.12-cip7: of the RDK dts's 5 #includes, r9a09g057.dtsi
# and gpio.h are present, but THREE are SST-downstream-only and missing:
#   - r9a09g057h4-evk-multi-os.dtsi   (cip has r9a09g057h44-rzv2h-evk.dts instead)
#   - dt-bindings/pinctrl/rzv2h-pinctrl.h
#   - dt-bindings/soc/renesas,rsci.h  (SST uses the RSCI serial driver; cip 6.12
#                                      uses SCIF/ttySC0 - serial nodes need rework)
# Path 1: adapt the vendor dts onto cip 6.12 (RSCI->SCIF serial, mainline rzv2h
# pinctrl), then add: SRC_URI:append:rzv2h-rdk = " file://<rdk-dts+makefile>.patch".
# Path 2 (fallback): vendor the SST Styhead BSP, where the dts builds as-is.
# Either path requires a build to verify.

# RZ/V2H Robot RDK device tree (first cut; see TODO above). The .dts ships as a
# plain readable file; the patch only registers its Makefile dtb entry. Copy the
# dts into the kernel tree before configure so the dtb target resolves.
SRC_URI:append:rzv2h-rdk = " file://r9a09g057h44-rzv2h-rdk.dts \
        file://0001-arm64-dts-renesas-add-rzv2h-rdk-to-makefile.patch"

do_configure:prepend:rzv2h-rdk() {
    install -m 0644 ${WORKDIR}/r9a09g057h44-rzv2h-rdk.dts \
        ${S}/arch/arm64/boot/dts/renesas/r9a09g057h44-rzv2h-rdk.dts
}

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
