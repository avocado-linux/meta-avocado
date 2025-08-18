# Basic description
DESCRIPTION = "Custom Device Tree and Kernel Modules for Seeed ReTerminal"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

DEPENDS += "virtual/kernel dtc-native"

# Specify compatible machine(s)
COMPATIBLE_MACHINE = "avocado-reterminal|avocado-reterminal-dm"

SRC_URI = "\
    https://raw.githubusercontent.com/Seeed-Studio/seeed-linux-dtoverlays/4f240f8ff9d3d3731050181dca1fb1f536ca03de/modules/ili9881d/ili9881d.c;name=ili9881d \
    file://Makefile \
"

SRC_URI[ili9881d.sha256sum] = "f6e43e192efdc6af4bf23e9f49acfe7d3eb7d7b46940e0055993423a8440d7e5"

S = "${WORKDIR}"

# Build the ili9881d kernel module
inherit module

# Add the module to the package
RPROVIDES:${PN} += "kernel-module-ili9881d"
