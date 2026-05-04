SUMMARY = "Peripheral firmware blobs for the Thundercomm RUBIK Pi 3"
DESCRIPTION = "Vendor-supplied firmware for the RUBIK Pi 3 onboard peripherals: \
Broadcom BCM43456 Wi-Fi/BT, LT9611UXC HDMI bridge, AW882xx audio amplifier, \
Renesas USB hub, and SD-UART 8987 combo chip."
LICENSE = "CLOSED"

PACKAGE_ARCH = "${MACHINE_ARCH}"

SRC_URI = " \
    file://aw882xx_acf.bin \
    file://config.txt \
    file://fw_bcm43456c5_ag.bin \
    file://lt9611uxc_fw.bin \
    file://nvram.txt \
    file://renesas_usb_fw.mem \
    file://sduart8987_combo.bin \
"

S = "${WORKDIR}"

do_install() {
    install -d ${D}${nonarch_base_libdir}/firmware
    install -m 0644 ${WORKDIR}/aw882xx_acf.bin       ${D}${nonarch_base_libdir}/firmware/
    install -m 0644 ${WORKDIR}/config.txt            ${D}${nonarch_base_libdir}/firmware/
    install -m 0644 ${WORKDIR}/fw_bcm43456c5_ag.bin  ${D}${nonarch_base_libdir}/firmware/
    install -m 0644 ${WORKDIR}/lt9611uxc_fw.bin      ${D}${nonarch_base_libdir}/firmware/
    install -m 0644 ${WORKDIR}/nvram.txt             ${D}${nonarch_base_libdir}/firmware/
    install -m 0644 ${WORKDIR}/renesas_usb_fw.mem    ${D}${nonarch_base_libdir}/firmware/
    install -m 0644 ${WORKDIR}/sduart8987_combo.bin  ${D}${nonarch_base_libdir}/firmware/
}

FILES:${PN} = "${nonarch_base_libdir}/firmware/*"
