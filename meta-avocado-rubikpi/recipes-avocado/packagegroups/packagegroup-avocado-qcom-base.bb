DESCRIPTION = "Packagegroup for base qcom images"
LICENSE = "Apache-2.0"

DEPENDS += "avocado-image-var"

inherit features_check

IMAGE_FEATURES += "post-install-logging"
REQUIRED_DISTRO_FEATURES = "pam systemd wayland vulkan"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = "${MACHINE_ESSENTIAL_EXTRA_RRECOMMENDS} \
        ${MACHINE_EXTRA_RDEPENDS} \
        packagegroup-qcom-data"
