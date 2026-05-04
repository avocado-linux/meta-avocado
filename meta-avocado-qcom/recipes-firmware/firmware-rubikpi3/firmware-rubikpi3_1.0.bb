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

    # brcmfmac firmware for the rubikpi3's BCM43456 (BCM4345/9 silicon rev).
    # Upstream `linux-firmware-bcm43455` is BCM4345/6 — a different rev; the
    # filename brcmfmac requests for our chip is `brcmfmac43456-sdio.*`,
    # which upstream linux-firmware does not ship at all. Repackage the
    # rubikpi-ai BCMDHD-format firmware under the brcmfmac filename
    # convention. (.bin content is the same; only the filename differs
    # between BCMDHD and brcmfmac driver expectations.)
    #
    # CLM regulatory blob: BCMDHD bundles CLM inside the .bin; brcmfmac wants
    # it separate. We don't ship one — most regdom enforcement still works
    # via wireless-regdb-static; if specific channels misbehave we can add
    # a CLM blob later.
    install -d ${D}${nonarch_base_libdir}/firmware/brcm
    install -m 0644 ${WORKDIR}/fw_bcm43456c5_ag.bin ${D}${nonarch_base_libdir}/firmware/brcm/brcmfmac43456-sdio.bin
    install -m 0644 ${WORKDIR}/nvram.txt            ${D}${nonarch_base_libdir}/firmware/brcm/brcmfmac43456-sdio.txt
    # CLM regulatory blob: BCMDHD bundles CLM inside the .bin; brcmfmac wants
    # it separate. We don't have a 43456 CLM, but the closely-related 43455
    # blob from upstream linux-firmware-bcm43455 works in practice (same
    # BCM4345 family). Symlink it so brcmfmac stops complaining at attach.
    ln -s brcmfmac43455-sdio.clm_blob ${D}${nonarch_base_libdir}/firmware/brcm/brcmfmac43456-sdio.clm_blob
}

# The CLM symlink target is provided by linux-firmware-bcm43455.
RDEPENDS:${PN} += "linux-firmware-bcm43455"

FILES:${PN} = " \
    ${nonarch_base_libdir}/firmware/* \
    ${nonarch_base_libdir}/firmware/brcm/* \
"
