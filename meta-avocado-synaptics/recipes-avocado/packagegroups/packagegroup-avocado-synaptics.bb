DESCRIPTION = "Packagegroup for inclusion in all Avocado Synaptics images"
LICENSE = "Apache-2.0"

do_image[deptask] = "do_image_complete"

inherit features_check

REQUIRED_DISTRO_FEATURES = ""

inherit packagegroup

RDEPENDS:${PN} = ""
