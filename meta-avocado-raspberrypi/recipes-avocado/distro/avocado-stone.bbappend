do_compile[depends] += "u-boot:do_deploy"
do_compile[depends] += "rpi-bootfiles:do_deploy"

DEPENDS += " jq-native mkfat-native fwup-native"

SRC_URI:append = " \
    file://${MACHINE_SHORT_NAME}/rootdisk.conf \
"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0644 ${WORKDIR}/${MACHINE_SHORT_NAME}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
}
