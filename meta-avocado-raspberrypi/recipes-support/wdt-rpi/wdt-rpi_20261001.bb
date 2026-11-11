SUMMARY = "Command-line tool for the Sequent Microsystems Super Watchdog HAT"
DESCRIPTION = "wdt reads the battery voltage and current and sets the watchdog period of the Super Watchdog with Battery Backup HAT for Raspberry Pi, over I2C."
HOMEPAGE = "https://github.com/SequentMicrosystems/wdt-rpi"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE;md5=1c7150793cb55769a1b529815603d01b"

# The Makefile links -lcrypt.
DEPENDS = "libxcrypt"

# The upstream project has no tags. PV is the date of the pinned commit.
PV = "20261001"
SRC_URI = "git://github.com/SequentMicrosystems/wdt-rpi.git;protocol=https;branch=master"
SRCREV = "f128e0e3e57833b7101deba1deee9e8cab5e38e5"

# Build only the wdt target. The Makefile sets CC, CFLAGS and LDFLAGS itself
# (CC = gcc, so it builds for the host), so pass the target values on the make
# command line.
# Its install target writes to /usr/local and sets the binary setuid root.
# do_install copies the file with mode 0755 instead, so only root can drive
# the I2C bus.
do_compile() {
    oe_runmake wdt CC="${CC}" CFLAGS="${CFLAGS}" LDFLAGS="${LDFLAGS}"
}

do_install() {
    install -D -m 0755 ${B}/wdt ${D}${bindir}/wdt
}

# The package is named after the recipe; callers ask for the tool by its command name.
RPROVIDES:${PN} += "wdt"
