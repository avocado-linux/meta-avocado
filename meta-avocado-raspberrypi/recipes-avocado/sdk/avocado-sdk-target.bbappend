FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

do_compile[depends] += "u-boot:do_deploy"
do_compile[depends] += "rpi-bootfiles:do_deploy"

RDEPENDS:${PN}:append = " \
  nativesdk-fwup \
  nativesdk-mkfat \
  nativesdk-rpi-usbboot \
  nativesdk-avocado-dtc-overlay \
"

# DEPENDS as well as RDEPENDS: RDEPENDS alone leaves the wrapper out of the
# build graph, so it never reaches the SDK feed and `avocado sdk install`
# fails with "No match for argument" once a runtime declares an overlay.
DEPENDS:append = " nativesdk-avocado-dtc-overlay"
