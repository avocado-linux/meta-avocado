FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

RDEPENDS:${PN}:append = " \
  nativesdk-mtools \
  nativesdk-dnsmasq \
  nativesdk-gptfdisk \
"
