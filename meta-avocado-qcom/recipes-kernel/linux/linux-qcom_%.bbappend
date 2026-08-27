FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

# No AUTOREV devupstream variant: it makes every parse run `git ls-remote`
# (see the BBMASK note in conf/layer.conf).
BBCLASSEXTEND:remove = "devupstream:target"

SRC_URI += " \
    file://avocado-core.cfg \
    file://avocado-extra.cfg \
"
SRC_URI:append:rubikpi3 = " file://rubikpi3-wifi.cfg file://rubikpi3-thermal.cfg file://qcs6490-thundercomm-rubikpi3.dts"

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

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
