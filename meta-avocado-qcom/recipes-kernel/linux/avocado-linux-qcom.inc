FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

# No AUTOREV devupstream variant: it makes every parse run `git ls-remote`
# (see the BBMASK note in conf/layer.conf).
BBCLASSEXTEND:remove = "devupstream:target"

SRC_URI += " \
    file://avocado-core.cfg \
    file://avocado-extra.cfg \
"
SRC_URI:append:rubikpi3 = " file://rubikpi3-wifi.cfg file://rubikpi3-thermal.cfg file://qcs6490-thundercomm-rubikpi3.dts"

# rb3gen2: disable the broken USB-C DP altmode output (mdss_dp @ae90000). Its
# retimer/altmode chain is incomplete, so the DP controller fails probe (-EINVAL)
# and stalls the whole msm DPU component aggregate -- the Adreno GPU never binds
# and there is no /dev/dri. It is disabled via a UKI-embedded device-tree overlay
# (qcs6490-rb3gen2-dp-disable.dtso, listed in AVOCADO_UKI_DTB_OVERLAYS), NOT as a
# base-dts change: UEFI's BoardInfoDxe DT-fixup panics at boot on a base dtb that
# has mdss_dp disabled and bricks the board into XBL dload, whereas sd-stub's
# leaner EFI_DT_FIXUP handles the overlaid embedded tree fine (same path
# kodiak-el2 and qcs6490-rb3gen2-staging ride). Applies to both the stock and
# PREEMPT_RT kernels (both require this .inc). Drop once the USB-C DP retimer
# path is described in the device tree.
SRC_URI:append:rb3gen2 = " file://qcs6490-rb3gen2-dp-disable.dtso"

# linux-qcom merges every file://*.cfg through find_cfgs() in its
# do_configure:prepend, so the fragments need no wiring beyond SRC_URI.

# RUBIK Pi 3 board dts: mainline arch/arm64/boot/dts/qcom/
# qcs6490-thundercomm-rubikpi3.dts as first merged (f055a39f68, Jan 2026),
# which is after the 6.18 branch this recipe tracks. Mainline had by then
# renamed sc7280.dtsi to kodiak.dtsi; the 6.18 tree still has sc7280.dtsi with
# the same labels, so that is the only edit. Dropped into the tree instead of
# carried as a patch so it never needs Makefile context fixups.
do_configure:prepend:rubikpi3() {
    install -m 0644 ${UNPACKDIR}/qcs6490-thundercomm-rubikpi3.dts ${S}/arch/arm64/boot/dts/qcom/
    grep -q 'qcs6490-thundercomm-rubikpi3.dtb' ${S}/arch/arm64/boot/dts/qcom/Makefile || \
        echo 'dtb-$(CONFIG_ARCH_QCOM)	+= qcs6490-thundercomm-rubikpi3.dtb' >> ${S}/arch/arm64/boot/dts/qcom/Makefile
}

# rb3gen2 DP-disable overlay: drop the overlay dts into the kernel tree and add
# it to the Makefile as a .dtbo (built as a /plugin/ overlay, deployed via
# KERNEL_DEVICETREE, merged into the UKI via AVOCADO_UKI_DTB_OVERLAYS). Mirrors
# the rubikpi3 board-dts handling above.
do_configure:prepend:rb3gen2() {
    install -m 0644 ${UNPACKDIR}/qcs6490-rb3gen2-dp-disable.dtso ${S}/arch/arm64/boot/dts/qcom/
    grep -q 'qcs6490-rb3gen2-dp-disable.dtbo' ${S}/arch/arm64/boot/dts/qcom/Makefile || \
        echo 'dtb-$(CONFIG_ARCH_QCOM)	+= qcs6490-rb3gen2-dp-disable.dtbo' >> ${S}/arch/arm64/boot/dts/qcom/Makefile
}

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
