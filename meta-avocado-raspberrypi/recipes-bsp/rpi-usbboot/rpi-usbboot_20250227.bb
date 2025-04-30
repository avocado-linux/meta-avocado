SUMMARY = "Raspberry Pi usbboot tool"
DESCRIPTION = "Tool to initialize Raspberry Pi CM4 and similar devices over USB"
HOMEPAGE = "https://github.com/raspberrypi/usbboot"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://LICENSE;md5=e3fc50a88d0a364313df4b21ef20c29e"

DEPENDS += "libusb1 pkgconfig-native vim-native"

PV = "20250227"
SRC_URI = "git://github.com/raspberrypi/usbboot.git;branch=master;protocol=https;gitsm=1"
SRCREV = "ecfb7222788735bd3b4714b0126f71025ae252da"

S = "${WORKDIR}/git"

inherit nativesdk

# Pass native build variables into the make environment
# EXTRA_OEMAKE += "'BUILD_CC=${BUILD_CC}' 'BUILD_CFLAGS=${BUILD_CFLAGS}' 'BUILD_LDFLAGS=${BUILD_LDFLAGS}'"

# Project uses Make directly, no configure step needed for the build itself
# do_configure[noexec] = "1"

do_compile() {
    oe_runmake
}

do_install() {
    # Create standard directories within the staging area first
    install -d ${D}${bindir}
    install -d ${D}${datadir}/rpiboot # Corresponds to $(INSTALL_PREFIX)/share/rpiboot

    # Use the Makefile's install target, overriding INSTALL_PREFIX to respect the staging directory D
    oe_runmake install DESTDIR=${D} INSTALL_PREFIX=${D}${prefix}
}

FILES:${PN} += "${datadir}/rpiboot"

# Skip the architecture check for this package, as it contains target firmware (start.elf)
INSANE_SKIP:${PN} += "arch"

BBCLASSEXTEND = "nativesdk"
