FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

SRC_URI:append = "\
  file://imx/rootdisk.conf \
  file://imx/stone-provision-sd.sh \
"

RDEPENDS:${PN}:append = " \
  nativesdk-fwup \
  nativesdk-mkfat \
  nativesdk-jq \
"

do_install:append() {
    install -d ${D}${SDKPATHNATIVE}/stone/${MACHINE_SHORT_NAME}
    install -m 0644 ${WORKDIR}/imx/rootdisk.conf ${D}${SDKPATHNATIVE}/stone/${MACHINE_SHORT_NAME}/rootdisk.conf
    install -m 0755 ${WORKDIR}/imx/stone-provision-sd.sh ${D}${SDKPATHNATIVE}/stone/${MACHINE_SHORT_NAME}/stone-provision.sh
}
