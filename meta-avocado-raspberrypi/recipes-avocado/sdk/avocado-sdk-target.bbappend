FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

do_compile[depends] += "u-boot:do_deploy"
do_compile[depends] += "rpi-bootfiles:do_deploy"

RDEPENDS:${PN}:append = " \
  nativesdk-fwup \
  nativesdk-mkfat \
  nativesdk-rpi-usbboot \
  nativesdk-avocado-dtc-overlay \
  nativesdk-swig \
"

# DEPENDS as well as RDEPENDS: RDEPENDS alone leaves the wrapper out of the
# build graph, so it never reaches the SDK feed and `avocado sdk install`
# fails with "No match for argument" once a runtime declares an overlay.
# nativesdk-swig is listed the same way: an extension that builds a Python
# binding in the SDK container (lgpio) needs it, and without the DEPENDS entry
# the feed never gets it.
DEPENDS:append = " nativesdk-avocado-dtc-overlay nativesdk-swig"
