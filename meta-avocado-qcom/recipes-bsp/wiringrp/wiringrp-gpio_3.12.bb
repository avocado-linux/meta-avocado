SUMMARY = "WiringPi-compatible /usr/bin/gpio CLI for RUBIK Pi 3"
DESCRIPTION = "Userspace GPIO control utility built against the wiringrp library. \
Provides the `gpio` command familiar from the Raspberry Pi WiringPi tooling, \
adapted to the RUBIK Pi 3 40-pin header."
LICENSE = "CLOSED"

# Source: https://github.com/rubikpi-ai/meta-rubikpi-bsp @ 227631ce94bb
DEPENDS += "libxcrypt wiringrp"

SRCPROJECT = "git://github.com/rubikpi-ai/WiringRP.git;protocol=https"
SRCBRANCH  = "main"
SRCREV = "4bfb0de9f6605978e55ee2e89374b2eb2a84358d"

SRC_URI = "${SRCPROJECT};branch=${SRCBRANCH}"

INSANE_SKIP:${PN} += "ldflags"

do_configure() {
}

do_compile() {
    oe_runmake -C ${S}/gpio EXTRA_CFLAGS="-I${S}/wiringPi -I${S}/devLib"
}

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${S}/gpio/gpio ${D}${bindir}
}

FILES:${PN} += "${bindir}"
