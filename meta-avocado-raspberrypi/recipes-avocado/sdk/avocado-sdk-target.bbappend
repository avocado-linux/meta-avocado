FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

do_compile[depends] += "u-boot:do_deploy"
do_compile[depends] += "rpi-bootfiles:do_deploy"

SRC_URI:append = "\
  file://${MACHINE_SHORT_NAME}/rootdisk.conf \
  file://${MACHINE_SHORT_NAME}/stone-provision.sh \
"

RDEPENDS:${PN}:append = " \
  nativesdk-fwup \
  nativesdk-mkfat \
  nativesdk-jq \
"

do_install:append() {
    install -d ${D}${SDKPATHNATIVE}/stone/${MACHINE_SHORT_NAME}
    install -m 0644 ${WORKDIR}/${MACHINE_SHORT_NAME}/rootdisk.conf ${D}${SDKPATHNATIVE}/stone/${MACHINE_SHORT_NAME}/rootdisk.conf
    install -m 0755 ${WORKDIR}/${MACHINE_SHORT_NAME}/stone-provision.sh ${D}${SDKPATHNATIVE}/stone/${MACHINE_SHORT_NAME}/stone-provision.sh
}
