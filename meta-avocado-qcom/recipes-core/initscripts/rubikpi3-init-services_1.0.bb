SUMMARY = "RUBIK Pi 3 init services for Wi-Fi (wpa_supplicant) and BT (BSA)"
DESCRIPTION = "Boot-time launchers for the rubikpi3's onboard radios. \
\
bt.sh + bt.service: power-on the BCM43456 BT chip via /sys/.../bt_reg, then \
launch the BSA Server (from rubikpi-bt-staticdev) on /dev/ttyHS7 with the \
BCM4345C5 hcd patch. \
\
wifi.sh + wifi.service: launch wpa_supplicant on wlan0 against \
/etc/wpa_supplicant.conf. systemd-networkd handles DHCP via the \
00-wireless-dhcp.network profile shipped by rubikpi-wifi."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

# Source: https://github.com/rubikpi-ai/meta-rubikpi-bsp @ 227631ce94bb
# (recipes-core/initscripts/{files/,initscripts_1.0.bbappend} — we import
# only the bt/wifi subset; rubikpi_boot.sh + the eeprom-mac/modem/sdcard/debug
# scripts are not relevant to avocado on rubikpi3.)

inherit systemd

PACKAGE_ARCH = "${MACHINE_ARCH}"

SRC_URI = " \
    file://bt.sh \
    file://bt.service \
    file://wifi.sh \
    file://wifi.service \
"

S = "${WORKDIR}"

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

# Note: SYSTEMD_AUTO_ENABLE is intentionally NOT set. These packages ship via
# the BSP extension; service enablement happens in bsp/<machine>/avocado.yaml
# under `enable_services:`. The recipe-side AUTO_ENABLE wouldn't take effect
# anyway — avocado's 99-default.preset has `disable *` and the extension
# rootfs is read-only.
SYSTEMD_PACKAGES = "${PN}-bt ${PN}-wifi"
SYSTEMD_SERVICE:${PN}-bt = "bt.service"
SYSTEMD_SERVICE:${PN}-wifi = "wifi.service"

PACKAGES = "${PN}-bt ${PN}-wifi"

RDEPENDS:${PN}-bt = "rubikpi-bt-staticdev"
RDEPENDS:${PN}-wifi = "wpa-supplicant rubikpi-wifi"

# Install scripts to ${libexecdir} (= /usr/libexec/) rather than /etc/. Avocado
# mounts /etc as a confext overlay with `noexec`, so anything systemd's
# ExecStart= points at on /etc fails with EACCES even with mode 0755. /usr is
# the sysext overlay which allows exec. The .service files ship with the
# original /etc/initscripts/ paths; rewrite them in install to match.
do_install() {
    install -d ${D}${libexecdir}/rubikpi3
    install -d ${D}${systemd_system_unitdir}

    install -m 0755 ${WORKDIR}/bt.sh   ${D}${libexecdir}/rubikpi3/bt.sh
    install -m 0644 ${WORKDIR}/bt.service ${D}${systemd_system_unitdir}/bt.service
    sed -i 's|/etc/initscripts/bt.sh|${libexecdir}/rubikpi3/bt.sh|g' \
        ${D}${systemd_system_unitdir}/bt.service

    install -m 0755 ${WORKDIR}/wifi.sh ${D}${libexecdir}/rubikpi3/wifi.sh
    install -m 0644 ${WORKDIR}/wifi.service ${D}${systemd_system_unitdir}/wifi.service
    sed -i 's|/etc/initscripts/wifi.sh|${libexecdir}/rubikpi3/wifi.sh|g' \
        ${D}${systemd_system_unitdir}/wifi.service
}

FILES:${PN}-bt = " \
    ${libexecdir}/rubikpi3/bt.sh \
    ${systemd_system_unitdir}/bt.service \
"
FILES:${PN}-wifi = " \
    ${libexecdir}/rubikpi3/wifi.sh \
    ${systemd_system_unitdir}/wifi.service \
"
