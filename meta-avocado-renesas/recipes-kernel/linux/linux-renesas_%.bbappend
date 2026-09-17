FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = " file://avocado-core.cfg \
        file://avocado-extra.cfg \
        file://panfrost.cfg"

# These GPU-enablement patches target the SolidRun rzv2n dtsi
# (rzv2n-hummingboard-iiot-common.dtsi); only apply on that board so they do not
# break other Renesas machines that share this bbappend.
SRC_URI:append:rzv2n-sr-som = " file://0001-dts-renesas-enable-mali-gpu.patch \
        file://0002-dts-renesas-add-fixed-gpu-regulator.patch"

# RZ/V2H Robot RDK device tree. Forward-ported onto linux-renesas 6.12
# (rz-6.12-cip7) from rzv2h-rdk-ver1.dts in Renesas-SST/linux-rz (branch
# ubuntu/rz-v2h-rdk, kernel 6.10); the SST-only includes it carried were replaced
# with their cip equivalents, so the shipped dts includes only r9a09g057.dtsi,
# rzg2l-pinctrl.h and gpio.h, all present in this kernel.
#
# The .dts ships as a plain readable file rather than inside a patch, so it stays
# reviewable and diffable against the vendor source; the patch beside it only
# registers the Makefile dtb entry. See docs/adding-a-machine-target.md section
# 10 for when to pick this shape over a single patch.
SRC_URI:append:rzv2h-rdk = " file://r9a09g057h44-rzv2h-rdk.dts \
        file://0001-arm64-dts-renesas-add-rzv2h-rdk-to-makefile.patch"

# Copy the dts into the kernel tree before configure so the dtb target resolves.
# Refuse to clobber a vendor-shipped file of the same name: once the BSP carries
# its own r9a09g057h44-rzv2h-rdk.dts, silently overwriting it would hide DT
# divergence, and the Makefile patch would then fail to apply for an unrelated
# reason (duplicate entry) pointing nowhere near the cause.
do_configure:prepend:rzv2h-rdk() {
    if [ -e ${S}/arch/arm64/boot/dts/renesas/r9a09g057h44-rzv2h-rdk.dts ]; then
        bbfatal "linux-renesas now ships arch/arm64/boot/dts/renesas/r9a09g057h44-rzv2h-rdk.dts. Drop the rzv2h-rdk dts and Makefile patch from this bbappend and use the vendor copy."
    fi
    install -m 0644 ${WORKDIR}/r9a09g057h44-rzv2h-rdk.dts \
        ${S}/arch/arm64/boot/dts/renesas/r9a09g057h44-rzv2h-rdk.dts
}

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
