# Basic description
DESCRIPTION = "Custom Device Tree for Seeed ReTerminal"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

inherit devicetree

DEPENDS += "virtual/kernel"

# Specify compatible machine(s)
COMPATIBLE_MACHINE = "avocado-reterminal|avocado-reterminal-dm"

SRCREV = "4f240f8ff9d3d3731050181dca1fb1f536ca03de"

# Location of the source .dts file
SRC_URI = "\
    https://raw.githubusercontent.com/Seeed-Studio/seeed-linux-dtoverlays/${SRCREV}/overlays/rpi/reTerminal-overlay.dts;downloadfilename=reTerminal.dts;name=reTerminal \
    https://raw.githubusercontent.com/Seeed-Studio/seeed-linux-dtoverlays/${SRCREV}/overlays/rpi/reTerminal-DM-overlay.dts;downloadfilename=reTerminal-DM.dts;name=reTerminal-DM \
"

SRC_URI[reTerminal.sha256sum] = "bc82b77cf82388c48254a9b34451d549fe4d6d486095ea49e9d38d8a05959c66"
SRC_URI[reTerminal-DM.sha256sum] = "66287767357dc3675c7bb383a4567b8e175753631f2a963a52fca79cf3e1f640"

S = "${WORKDIR}"

DT_FILES_PATH = "${WORKDIR}"

# Install the .dtbo files to the boot partition overlays directory
do_install() {
    install -d ${D}${nonarch_base_libdir}/firmware/overlays
    install -m 0644 ${B}/reTerminal.dtbo ${D}${nonarch_base_libdir}/firmware/overlays/
    install -m 0644 ${B}/reTerminal-DM.dtbo ${D}${nonarch_base_libdir}/firmware/overlays/
}

FILES:${PN} += "${nonarch_base_libdir}/firmware/overlays/"
