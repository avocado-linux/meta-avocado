inherit stone

do_compile[depends] += "u-boot:do_deploy"

DEPENDS += " jq-native mkfat-native fwup-native"

SRC_URI += " \
    file://rootdisk.conf \
    file://stone-provision-peridio.sh \
"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0644 ${UNPACKDIR}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
  install -m 0755 ${UNPACKDIR}/stone-provision-peridio.sh ${DEPLOYDIR}/stone-provision-peridio.sh
}
