DESCRIPTION = "Packagegroup for inclusion in Avocado reTerminal SDKs"
LICENSE = "Apache-2.0"

inherit packagegroup

RDEPENDS:${PN} = " \
  nativesdk-rpi-usbboot \
"
