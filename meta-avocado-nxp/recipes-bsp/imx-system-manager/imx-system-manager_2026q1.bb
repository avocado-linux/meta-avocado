SUMMARY = "i.MX System Manager Firmware"
DESCRIPTION = "\
The System Manager (SM) is a firmware that runs on a Cortex-M processor on \
many NXP i.MX processors. The Cortex-M is the boot core, runs the boot ROM \
which loads the SM (and other boot code), and then branches to the SM. The \
SM then configures some aspects of the hardware such as isolation mechanisms \
and then starts other cores in the system. After starting these cores, it \
enters a service mode where it provides access to clocking, power, sensor, \
and pin control via a client RPC API based on ARM's System Control and \
Management Interface (SCMI)."
LICENSE = "BSD-3-Clause"
LIC_FILES_CHKSUM = "file://LICENSE.txt;md5=f2a70813bc08547f509361c08b718861"

SRC_URI = "${IMX_SYSTEM_MANAGER_SRC};branch=${SRCBRANCH}"
IMX_SYSTEM_MANAGER_SRC ?= "git://github.com/nxp-imx/imx-sm.git;protocol=https"
SRCBRANCH = "master"
SRCREV = "c450f53974ea1df826970ad399cb338625b5638d"

S = "${WORKDIR}/git"

# Set generic compiler for system manager core
INHIBIT_DEFAULT_DEPS = "1"
DEPENDS = "${SM_COMPILER}"
SM_COMPILER ?= "gcc-arm-none-eabi-native"

inherit deploy

# Set monitor mode for none, one, or two
PACKAGECONFIG[m0] = "M=0,,,,,m1 m2"
PACKAGECONFIG[m1] = ",,,,,m0 m2"
PACKAGECONFIG[m2] = "M=2,,,,,m0 m1"
PACKAGECONFIG ??= "m2"

SYSTEM_MANAGER_CONFIG ?= "INVALID"

LDFLAGS[unexport] = "1"

EXTRA_OEMAKE = " \
    V=y \
    SM_CROSS_COMPILE=arm-none-eabi- \
    ${PACKAGECONFIG_CONFARGS} \
"

do_configure() {
    oe_runmake config=${SYSTEM_MANAGER_CONFIG} clean
    oe_runmake config=${SYSTEM_MANAGER_CONFIG} cfg
}

do_compile() {
    oe_runmake config=${SYSTEM_MANAGER_CONFIG}
}

do_install[noexec] = "1"

addtask deploy after do_compile
do_deploy() {
    install -D -p -m 0644 \
        ${B}/build/${SYSTEM_MANAGER_CONFIG}/${SYSTEM_MANAGER_FIRMWARE_BASENAME}.bin \
        ${DEPLOYDIR}/${SYSTEM_MANAGER_FIRMWARE_BASENAME}-${SYSTEM_MANAGER_CONFIG}.bin
}

COMPATIBLE_MACHINE = "avocado-imx95-frdm"
