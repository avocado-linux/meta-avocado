do_compile[depends] += "u-boot:do_deploy"
do_compile[depends] += "rpi-bootfiles:do_deploy"

DEPENDS += " jq-native mkfat-native fwup-native"

SRC_URI += " \
    file://${MACHINE_SHORT_NAME}/rootdisk.conf \
    file://${MACHINE_SHORT_NAME}/stone-provision-img.sh \
    file://${MACHINE_SHORT_NAME}/stone-provision-sd.sh \
"

SRC_URI:reterminal:reterminal-dm:fr202 += " \
    file://${MACHINE_SHORT_NAME}/rootdisk.conf \
    file://${MACHINE_SHORT_NAME}/stone-provision-img.sh \
    file://${MACHINE_SHORT_NAME}/stone-provision-usb.sh \
"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0644 ${WORKDIR}/${MACHINE_SHORT_NAME}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
  install -m 0755 ${WORKDIR}/${MACHINE_SHORT_NAME}/stone-provision-img.sh ${DEPLOYDIR}/stone-provision-img.sh
  install -m 0755 ${WORKDIR}/${MACHINE_SHORT_NAME}/stone-provision-sd.sh ${DEPLOYDIR}/stone-provision-sd.sh
}

do_deploy:append:reterminal:reterminal-dm:fr202() {
  install -d ${DEPLOYDIR}
  install -m 0644 ${WORKDIR}/${MACHINE_SHORT_NAME}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
  install -m 0755 ${WORKDIR}/${MACHINE_SHORT_NAME}/stone-provision-img.sh ${DEPLOYDIR}/stone-provision-img.sh
  install -m 0755 ${WORKDIR}/${MACHINE_SHORT_NAME}/stone-provision-usb.sh ${DEPLOYDIR}/stone-provision-usb.sh
}
