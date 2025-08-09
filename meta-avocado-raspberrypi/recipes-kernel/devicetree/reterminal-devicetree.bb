# Basic description
DESCRIPTION = "Custom Device Tree for Seeed ReTerminal"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

inherit devicetree

DEPENDS += "virtual/kernel"

# Specify compatible machine(s)
COMPATIBLE_MACHINE = "avocado-reterminal"

# Location of the source .dts file
SRC_URI = "https://raw.githubusercontent.com/Seeed-Studio/seeed-linux-dtoverlays/4f240f8ff9d3d3731050181dca1fb1f536ca03de/overlays/rpi/reTerminal-overlay.dts;downloadfilename=reTerminal.dts"
SRC_URI[sha256sum] = "bc82b77cf82388c48254a9b34451d549fe4d6d486095ea49e9d38d8a05959c66"

S = "${WORKDIR}"

DT_FILES_PATH = "${WORKDIR}"

# Install the .dtbo file to the boot partition overlays directory
do_install() {
    install -d ${D}${nonarch_base_libdir}/firmware/overlays
    install -m 0644 ${B}/reTerminal.dtbo ${D}${nonarch_base_libdir}/firmware/overlays/
}

FILES:${PN} += "${nonarch_base_libdir}/firmware/overlays/"
