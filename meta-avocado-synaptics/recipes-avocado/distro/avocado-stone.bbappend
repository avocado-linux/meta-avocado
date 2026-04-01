do_compile[depends] += "syna-u-boot:do_deploy"

DEPENDS += " jq-native mkfat-native fwup-native"

SRC_URI += " \
    file://rootdisk.conf \
"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0644 ${WORKDIR}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
}
