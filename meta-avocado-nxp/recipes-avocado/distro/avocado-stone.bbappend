do_compile[depends] += "u-boot-imx:do_deploy"
do_compile[depends] += "imx-boot:do_deploy"

DEPENDS += " jq-native mkfat-native fwup-native"

SRC_URI += " \
    file://imx/rootdisk.conf \
    file://imx/stone-provision-img.sh \
    file://imx/stone-provision-sd.sh \
"

do_deploy:append() {
  install -d ${DEPLOYDIR}
  install -m 0644 ${WORKDIR}/imx/rootdisk.conf ${DEPLOYDIR}/rootdisk.conf
  install -m 0755 ${WORKDIR}/imx/stone-provision-img.sh ${DEPLOYDIR}/stone-provision-img.sh
  install -m 0755 ${WORKDIR}/imx/stone-provision-sd.sh ${DEPLOYDIR}/stone-provision-sd.sh
}
