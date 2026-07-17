DESCRIPTION = "Packagegroup for the Avocado browsers feature group"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  ${@bb.utils.contains('DISTRO_FEATURES', 'opengl wayland', 'chromium-ozone-wayland', '', d)} \
"
