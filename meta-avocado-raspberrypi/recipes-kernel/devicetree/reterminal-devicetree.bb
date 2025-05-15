# Basic description
DESCRIPTION = "Custom Device Tree for Seeed ReTerminal"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

inherit devicetree

DEPENDS += "virtual/kernel"

# Specify compatible machine(s)
COMPATIBLE_MACHINE = "avocado-reterminal"

# Location of the source .dts file
SRC_URI = "https://raw.githubusercontent.com/Seeed-Studio/seeed-linux-dtoverlays/master/overlays/rpi/reTerminal-overlay.dts;downloadfilename=reTerminal.dts"
SRC_URI[sha256sum] = "f25afb59575d68051d48f5d069de3bed92de094a4ab50a8c5514fc3cdf3029b0"

S = "${WORKDIR}"

DT_FILES_PATH = "${WORKDIR}"

# Install the .dtbo file to the boot partition overlays directory
do_install() {
    install -d ${D}${nonarch_base_libdir}/firmware/overlays
    install -m 0644 ${B}/reTerminal.dtbo ${D}${nonarch_base_libdir}/firmware/overlays/
}

FILES:${PN} += "${nonarch_base_libdir}/firmware/overlays/"
