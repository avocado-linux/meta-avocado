SUMMARY = "WiringPi-compatible GPIO library for RUBIK Pi 3"
DESCRIPTION = "Port of the Raspberry Pi WiringPi C library for the RUBIK Pi 3 \
40-pin header. Ships libwiringPi.so, libwiringPiDev.so and matching headers \
under /usr/include — drop-in for code originally written against WiringPi."
LICENSE = "CLOSED"

# Source: https://github.com/rubikpi-ai/meta-rubikpi-bsp @ 227631ce94bb
DEPENDS += "libxcrypt"

SRCPROJECT = "git://github.com/rubikpi-ai/WiringRP.git;protocol=https"
SRCBRANCH  = "main"
SRCREV = "4bfb0de9f6605978e55ee2e89374b2eb2a84358d"

SRC_URI = "${SRCPROJECT};branch=${SRCBRANCH}"

S = "${WORKDIR}/git"

INSANE_SKIP:${PN} += "ldflags"

do_compile() {
    oe_runmake -C ${S}/wiringPi
    oe_runmake -C ${S}/devLib EXTRA_CFLAGS="-I${S}/wiringPi"
}

do_install() {
    install -d ${D}/usr/lib
    install -d ${D}/usr/include

    cp -r ${S}/wiringPi/libwiringPi.so.${PV} ${D}/usr/lib/libwiringPi.so
    cp -r ${S}/wiringPi/*.h ${D}/usr/include/

    cp -r ${S}/devLib/libwiringPiDev.so.${PV} ${D}/usr/lib/libwiringPiDev.so
    cp -r ${S}/devLib/*.h ${D}/usr/include/
}

FILES:${PN}-dev = ""

FILES:${PN} += " \
    /usr/lib/libwiringPi.so \
    /usr/lib/libwiringPiDev.so \
"
FILES:${PN} += "/usr/include/*.h"
