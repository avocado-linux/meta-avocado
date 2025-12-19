FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

do_compile[depends] += "u-boot:do_deploy"
do_compile[depends] += "rpi-bootfiles:do_deploy"

RDEPENDS:${PN}:append = " \
  nativesdk-fwup \
  nativesdk-mkfat \
  nativesdk-rpi-usbboot \
"

SRC_URI:append = " file://avocado-deploy-rpi"

do_install:append() {
  install -m 755 ${WORKDIR}/avocado-deploy-rpi ${D}${SDKPATHNATIVE}${bindir}/avocado-deploy-${MACHINE_SHORT_NAME}
}

FILES:${PN}:append = " ${SDKPATHNATIVE}${bindir}/avocado-deploy-${MACHINE_SHORT_NAME}"
