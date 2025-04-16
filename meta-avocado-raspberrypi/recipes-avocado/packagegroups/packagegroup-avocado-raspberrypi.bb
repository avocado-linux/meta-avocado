DESCRIPTION = "Packagegroup for inclusion in all Avocado RaspberryPi images"
LICENSE = "Apache-2.0"

inherit features_check

IMAGE_FEATURES += ""
REQUIRED_DISTRO_FEATURES = ""

inherit packagegroup

RDEPENDS:${PN} = ""
