# Basic description
DESCRIPTION = "Custom Kernel Module for Seeed ReTerminal PCF8563W"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

DEPENDS += "virtual/kernel dtc-native"

# Specify compatible machine(s)
COMPATIBLE_MACHINE = "avocado-reterminal|avocado-reterminal-dm"

SRCREV = "e9d88ebad195561a0b788d36f59bc67a7bcc697b"

SRC_URI = "\
    https://raw.githubusercontent.com/Seeed-Studio/seeed-linux-dtoverlays/${SRCREV}/modules/rtc-pcf8563w/rtc-pcf8563w.c;name=rtc-pcf8563w \
    file://Makefile \
"

SRC_URI[rtc-pcf8563w.sha256sum] = "4d75efac1b586fe2f62bac9719987078a46a4f3f4dff18b40df6b00f4c26fbe3"

S = "${WORKDIR}"

# Build the rtc-pcf8563w kernel module
inherit module

# Add the module to the package
RPROVIDES:${PN} += "kernel-module-rtc-pcf8563w"
