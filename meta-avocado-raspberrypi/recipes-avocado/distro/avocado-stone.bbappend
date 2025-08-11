do_compile[depends] += "u-boot:do_deploy"
do_compile[depends] += "rpi-bootfiles:do_deploy"

DEPENDS += " jq-native mkfat-native fwup-native"

SRC_URI += " \
    file://${MACHINE_SHORT_NAME}/rootdisk.conf \
    file://${MACHINE_SHORT_NAME}/stone-provision.sh \
"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0644 ${WORKDIR}/${MACHINE_SHORT_NAME}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
  install -m 0755 ${WORKDIR}/${MACHINE_SHORT_NAME}/stone-provision.sh ${DEPLOYDIR}/stone-provision.sh
}
