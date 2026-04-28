do_compile[depends] += "syna-u-boot:do_deploy"

DEPENDS += " jq-native mkfat-native fwup-native"

SRC_URI += " \
    file://rootdisk.conf \
    file://stone-provision-synaimg.sh \
    file://stone-provision-usb-emmc.sh \
"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0644 ${WORKDIR}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
  install -m 0755 ${WORKDIR}/stone-provision-synaimg.sh ${DEPLOYDIR}/stone-provision-synaimg.sh
  install -m 0755 ${WORKDIR}/stone-provision-usb-emmc.sh ${DEPLOYDIR}/stone-provision-usb-emmc.sh
}
