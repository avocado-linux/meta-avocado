FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI = "git://github.com/rubikpi-ai/prebuilt;protocol=https;branch=BP-BINs \
    file://aw882xx_acf.bin \
    file://config.txt \
    file://fw_bcm43456c5_ag.bin \
    file://lt9611uxc_fw.bin \
    file://nvram.txt \
    file://renesas_usb_fw.mem \
    file://sduart8987_combo.bin"

SRCREV = "582e89422b3efd5a09aba3d584beef4083b70d14"

S = "${WORKDIR}/git"

DEPENDS += "unzip-native"

do_extract_bootbin() {
    unzip "${S}/${HLOSFIRMWARE}.zip" -d "${WORKDIR}"
}

do_extract_bootbin[depends] += "unzip-native:do_populate_sysroot"
addtask extract_bootbin after do_unpack before do_patch

do_install[postfuncs] += "install_fw_blobs"

install_fw_blobs() {
    install -d ${D}${nonarch_base_libdir}/firmware
    install -m 0644 ${WORKDIR}/aw882xx_acf.bin ${D}${nonarch_base_libdir}/firmware/
    install -m 0644 ${WORKDIR}/config.txt ${D}${nonarch_base_libdir}/firmware/
    install -m 0644 ${WORKDIR}/fw_bcm43456c5_ag.bin ${D}${nonarch_base_libdir}/firmware/
    install -m 0644 ${WORKDIR}/lt9611uxc_fw.bin ${D}${nonarch_base_libdir}/firmware/
    install -m 0644 ${WORKDIR}/nvram.txt ${D}${nonarch_base_libdir}/firmware/
    install -m 0644 ${WORKDIR}/renesas_usb_fw.mem ${D}${nonarch_base_libdir}/firmware/
    install -m 0644 ${WORKDIR}/sduart8987_combo.bin ${D}${nonarch_base_libdir}/firmware/
    chown -R root:root ${D}${nonarch_base_libdir}/firmware || true
}

FILES:${PN} += "${nonarch_base_libdir}/firmware/*"
