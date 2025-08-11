do_compile[depends] += "u-boot-imx:do_deploy"
do_compile[depends] += "imx-boot:do_deploy"

DEPENDS += " jq-native mkfat-native fwup-native"

SRC_URI += " \
    file://imx/rootdisk.conf \
    file://imx/stone-provision.sh \
"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0644 ${WORKDIR}/imx/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
  install -m 0755 ${WORKDIR}/imx/stone-provision.sh ${DEPLOYDIR}/stone-provision.sh
}
