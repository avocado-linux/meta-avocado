SUMMARY = "systemd-networkd DHCP profile for the RUBIK Pi 3 onboard Wi-Fi (wlan0)"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

# Source: https://github.com/rubikpi-ai/meta-rubikpi-bsp @ 227631ce94bb
SRC_URI = "file://00-wireless-dhcp.network"

PACKAGE_ARCH = "${MACHINE_ARCH}"

# File-only recipe: nothing lands in the default S (${UNPACKDIR}/${BP}),
# which oe-core now warns about in do_unpack. The files are installed from
# ${UNPACKDIR} directly.
S = "${UNPACKDIR}"

do_install() {
    install -d ${D}${sysconfdir}/systemd/network
    install -m 0644 ${UNPACKDIR}/00-wireless-dhcp.network ${D}${sysconfdir}/systemd/network/00-wireless-dhcp.network
}

FILES:${PN} += "${sysconfdir}/systemd/network/00-wireless-dhcp.network"
