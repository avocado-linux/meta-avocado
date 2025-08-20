# Basic description
DESCRIPTION = "Custom Kernel Module for Seeed ReTerminal LTR30x"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

DEPENDS += "virtual/kernel dtc-native"

# Specify compatible machine(s)
COMPATIBLE_MACHINE = "avocado-reterminal|avocado-reterminal-dm"

SRC_URI = "\
    https://raw.githubusercontent.com/Seeed-Studio/seeed-linux-dtoverlays/4f240f8ff9d3d3731050181dca1fb1f536ca03de/modules/ltr30x/ltr30x.c;name=ltr30x \
    file://Makefile \
"

SRC_URI[ltr30x.sha256sum] = "c9106e35b85a87bd4c1ae11e69c6f2609913b515e445805c144707642c21b728"

S = "${WORKDIR}"

# Build the ltr30x kernel module
inherit module

# Add the module to the package
RPROVIDES:${PN} += "kernel-module-ltr30x"
