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

do_configure() {
}

# gpio/Makefile hardcodes INCLUDE=-I$(DESTDIR)$(PREFIX)/include and
# LDFLAGS=-L$(DESTDIR)$(PREFIX)/lib, which default to /usr/local -- a host
# path OE's gcc rejects outright:
#   error: include location "/usr/local/include" is unsafe for
#   cross-compilation [-Werror=poison-system-directories]
# (wiringPi/Makefile escapes this only because it uses INCLUDE = -I.)
# Both are plain '=' assignments, so the environment cannot override them;
# make command-line variables can. Point INCLUDE at the in-tree headers and
# hand the Makefile OE's real CFLAGS/LDFLAGS -- the latter carries
# --hash-style=gnu, so the ldflags QA skip this recipe used to need is gone.
do_compile() {
    oe_runmake -C ${S}/gpio \
        INCLUDE="-I${S}/wiringPi -I${S}/devLib" \
        LDFLAGS="${LDFLAGS}" \
        EXTRA_CFLAGS="${CFLAGS}"
}

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${S}/gpio/gpio ${D}${bindir}
}

FILES:${PN} += "${bindir}"
