FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
FILESEXTRAPATHS:prepend := "${@':'.join(['%s/stone' % layer for layer in d.getVar('BBLAYERS').split()])}:"

RDEPENDS:${PN}:append:avocado-synaptics = " \
    nativesdk-android-tools \
    nativesdk-android-tools-fstools \
    nativesdk-astra-update \
    nativesdk-astra-usbboot-images \
    nativesdk-fwup \
"
