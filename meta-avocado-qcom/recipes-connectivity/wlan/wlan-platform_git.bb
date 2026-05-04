DESCRIPTION = "QCOM WLAN platform driver"
LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/${LICENSE};md5=801f80980d171dd6425610833a22dbe6"

inherit module

DEPENDS += "coreutils-native"

SRCPROJECT = "git://git.codelinaro.org/clo/le/platform/vendor/qcom-opensource/wlan/platform.git;protocol=https"
SRCBRANCH  = "wlan-platform.qclinux.1.0.r2-rel"
SRCREV     = "40461f61190230a2ad3111f94b5ce4ac78bef355"

SRC_URI = "${SRCPROJECT};branch=${SRCBRANCH};destsuffix=wlan/platform"

S = "${UNPACKDIR}/wlan/platform"

RPROVIDES:${PN} += "kernel-module-wlan-platform"

EXTRA_OEMAKE += "MACHINE='${MACHINE}'"

python __anonymous () {
    machine = d.getVar('MACHINE') or ""
    if machine in ('qcs8550', 'qcs8650'):
        d.appendVar('EXTRA_OEMAKE', " CONFIG_PINCTRL_MSM=n WLAN_PLATFORM_DRIVER_CNSS=y")
    elif ("qcs6490" in machine) or ("qcm6490" in machine) or ("rubikpi3" in machine) or ("avocado-rubikpi3" in machine):
        d.appendVar('EXTRA_OEMAKE', " CONFIG_PINCTRL_MSM=n WLAN_PLATFORM_DRIVER_CNSS=y WLAN_PLATFORM_DRIVER_ICNSS=y")
}

MAKE_TARGETS = "modules"
MODULES_INSTALL_TARGET = "modules_install"
INSANE_SKIP:${PN}-dev = "1"
KERNEL_MODULE_AUTOLOAD += "cnss_nl"
