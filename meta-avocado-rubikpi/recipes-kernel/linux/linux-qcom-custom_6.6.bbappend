LIC_FILES_CHKSUM = "file://COPYING;md5=6bc538ed5bd9a7fc9398086aedcd7e46"

SRC_URI = "git://git@github.com/rubikpi-ai/linux;protocol=https;nobranch=1 \
           ${@bb.utils.contains('DISTRO_FEATURES', 'selinux', ' file://selinux.cfg', '', d)} \
           ${@bb.utils.contains('DISTRO_FEATURES', 'selinux', ' file://selinux_debug.cfg', '', d)} \
           ${@bb.utils.contains('DISTRO_FEATURES', 'smack', ' file://smack.cfg', '', d)} \
           ${@bb.utils.contains('DISTRO_FEATURES', 'smack', ' file://smack_debug.cfg', '', d)} \
           file://0001-QCLINUX-Add-support-to-compile-msm_display.ko.patch \
           file://0002-QCLINUX-arm64-dts-qcom-Disable-eMMC-ICE.patch \
           file://0003-PENDING-arm64-dts-qcom-Add-EEPROM-support-for-IQ-907.patch \
           file://0004-QCLINUX-net-stmmac-Add-EEPROM-support-to-driver.patch \
           file://0005-kernel-arm64-dts-qcom-enable-EEPROM-Client-Driver.patch \
           file://0006-kernel-config-qcom-enable-AT24-EEPROM-driver.patch"

SRCREV = "75a16b050e861e6bc41bcd5fd1358d2f6ba7f3ce"

S = "${WORKDIR}/git"

do_configure:append() {
    kernel_conf_variable BTRFS_FS y
    kernel_conf_variable SQUASHFS y
    kernel_conf_variable SQUASHFS_ZSTD y
    kernel_conf_variable LOCALVERSION ""
    kernel_conf_variable LOCALVERSION_AUTO n
    kernel_conf_variable AUDIT n
    kernel_conf_variable USB_DWC3 n
    oe_runmake -C ${S} O=${B} savedefconfig && cp ${B}/defconfig ${WORKDIR}/defconfig.saved
}

KERNEL_CONFIG_FRAGMENTS:append = " ${S}/arch/arm64/configs/rubikpi3.config"
