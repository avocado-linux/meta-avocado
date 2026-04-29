DESCRIPTION = "Packagegroup for extra inclusions in Avocado RaspberryPi images"
LICENSE = "Apache-2.0"

inherit features_check

IMAGE_FEATURES += ""
REQUIRED_DISTRO_FEATURES = ""

inherit packagegroup nospdx

RDEPENDS:${PN} = " \
  userlandtools \
  python3-gpiozero \
  ${MACHINE_EXTRA_RRECOMMENDS} \
"
