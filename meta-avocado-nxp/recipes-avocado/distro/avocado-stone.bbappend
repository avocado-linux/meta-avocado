do_compile[depends] += "u-boot-imx:do_deploy"
do_compile[depends] += "imx-boot:do_deploy"

DEPENDS += " jq-native mkfat-native fwup-native"

SRC_URI += " \
    file://rootdisk.conf \
"

SRC_URI:append:stone-uuu-emmc = " \
    file://stone-provision-uuu-emmc.sh \
"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0644 ${UNPACKDIR}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
}

do_deploy:append:stone-uuu-emmc() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${UNPACKDIR}/stone-provision-uuu-emmc.sh ${DEPLOYDIR}/stone-provision-uuu-emmc.sh
}
