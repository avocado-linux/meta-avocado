FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

do_compile[depends] += "u-boot:do_deploy"
do_compile[depends] += "firmware-pack:do_deploy"
do_compile[depends] += "flash-writer:do_deploy"

RDEPENDS:${PN}:append = " \
  nativesdk-fwup \
  nativesdk-mkfat \
"
