DESCRIPTION = "Packagegroup for inclusion in all Avocado NXP FRDM images"
LICENSE = "Apache-2.0"

do_image[deptask] = "do_image_complete"

inherit features_check

IMAGE_FEATURES += "splash hwcodecs"
REQUIRED_DISTRO_FEATURES = "opengl"

inherit packagegroup

RDEPENDS:${PN} = ""
