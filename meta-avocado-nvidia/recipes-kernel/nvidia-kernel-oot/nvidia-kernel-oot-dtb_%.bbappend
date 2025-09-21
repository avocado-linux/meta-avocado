FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append:icam-540 = " file://tegra234-p3768-0000+p3767-0001-icam-540.dtb"

do_deploy:prepend:icam-540() {
    install -d ${STAGING_DIR_HOST}/boot/devicetree
    install -m 0644 ${WORKDIR}/tegra234-p3768-0000+p3767-0001-icam-540.dtb ${STAGING_DIR_HOST}/boot/devicetree/
}
