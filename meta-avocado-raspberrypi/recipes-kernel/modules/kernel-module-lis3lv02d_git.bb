# Basic description
DESCRIPTION = "Custom Kernel Module for Seeed ReTerminal LIS3LV02D"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

DEPENDS += "virtual/kernel dtc-native"

# Specify compatible machine(s)
COMPATIBLE_MACHINE = "avocado-reterminal|avocado-reterminal-dm"

SRCREV = "e9d88ebad195561a0b788d36f59bc67a7bcc697b"

SRC_URI = "\
    https://raw.githubusercontent.com/Seeed-Studio/seeed-linux-dtoverlays/${SRCREV}/modules/lis3lv02d/lis3lv02d.c;name=lis3lv02d \
    file://Makefile \
"

SRC_URI[lis3lv02d.sha256sum] = "c1aaf749144ce78711d88a8955efc17d1434c681398a303cf2f481011e5deff7"

S = "${WORKDIR}"

# Build the lis3lv02d kernel module
inherit module

# Add the module to the package
RPROVIDES:${PN} += "kernel-module-lis3lv02d"
