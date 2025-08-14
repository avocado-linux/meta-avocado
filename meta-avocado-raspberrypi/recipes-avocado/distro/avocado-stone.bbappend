do_compile[depends] += "u-boot:do_deploy"
do_compile[depends] += "rpi-bootfiles:do_deploy"

DEPENDS += " jq-native mkfat-native fwup-native"

SRC_URI:append = " \
    file://${MACHINE_SHORT_NAME}/rootdisk.conf \
"

SRC_URI:append:stone-img = " \
    file://${MACHINE_SHORT_NAME}/stone-provision-img.sh \
"

SRC_URI:append:stone-sd = " \
    file://${MACHINE_SHORT_NAME}/stone-provision-sd.sh \
"

SRC_URI:append:stone-usb = " \
    file://${MACHINE_SHORT_NAME}/stone-provision-usb.sh \
"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0644 ${WORKDIR}/${MACHINE_SHORT_NAME}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
}

do_deploy:append:stone-sd() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/${MACHINE_SHORT_NAME}/stone-provision-sd.sh ${DEPLOYDIR}/stone-provision-sd.sh
}

do_deploy:append:stone-usb() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/${MACHINE_SHORT_NAME}/stone-provision-usb.sh ${DEPLOYDIR}/stone-provision-usb.sh
}

do_deploy:append:stone-img() {
  install -d ${DEPLOYDIR}
  install -m 0755 ${WORKDIR}/${MACHINE_SHORT_NAME}/stone-provision-img.sh ${DEPLOYDIR}/stone-provision-img.sh
}
