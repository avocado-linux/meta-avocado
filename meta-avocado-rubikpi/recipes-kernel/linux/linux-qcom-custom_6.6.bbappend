LIC_FILES_CHKSUM = "file://COPYING;md5=6bc538ed5bd9a7fc9398086aedcd7e46"

SRC_URI = "git://git@github.com/rubikpi-ai/linux;protocol=https;nobranch=1 \
           ${@bb.utils.contains('DISTRO_FEATURES', 'selinux', ' file://selinux.cfg', '', d)} \
           ${@bb.utils.contains('DISTRO_FEATURES', 'selinux', ' file://selinux_debug.cfg', '', d)} \
           ${@bb.utils.contains('DISTRO_FEATURES', 'smack', ' file://smack.cfg', '', d)} \
           ${@bb.utils.contains('DISTRO_FEATURES', 'smack', ' file://smack_debug.cfg', '', d)} \
           file://0001-QCLINUX-Add-support-to-compile-msm_display.ko.patch \
           file://0002-PENDING-misc-fastrpc-Return-on-argument-copy-failure.patch \
           file://0003-QCLINUX-arm64-dts-qcom-Add-board-id-and-msm-id-for-R.patch"

SRCREV = "8c1599030840bcca335c12a08c7485a885345d62"

S = "${WORKDIR}/git"

do_configure:append() {
    kernel_conf_variable BTRFS_FS y
    kernel_conf_variable SQUASHFS y
    kernel_conf_variable SQUASHFS_ZSTD y
    kernel_conf_variable LOCALVERSION ""
    kernel_conf_variable LOCALVERSION_AUTO n
    kernel_conf_variable AUDIT n
    kernel_conf_variable USB_DWC3 n
    kernel_conf_variable CRYPTO_LZ4 m
    kernel_conf_variable ZRAM m
    oe_runmake -C ${S} O=${B} savedefconfig && cp ${B}/defconfig ${WORKDIR}/defconfig.saved
}

KERNEL_CONFIG_FRAGMENTS:append = " ${S}/arch/arm64/configs/rubikpi3.config"
