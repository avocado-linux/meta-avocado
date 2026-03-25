# Ensure firmware artifacts are deployed before stone runs
do_compile[depends] += "firmware-pack:do_deploy"
do_compile[depends] += "flash-writer:do_deploy"
do_compile[depends] += "u-boot:do_deploy"

DEPENDS += " jq-native mkfat-native fwup-native"

SRC_URI:append = " \
    file://rootdisk.conf \
"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0644 ${WORKDIR}/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
}
