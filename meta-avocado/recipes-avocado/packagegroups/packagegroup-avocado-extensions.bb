DESCRIPTION = "Packagegroup for Avocado extensions"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  avocado-extension-debug-tweaks \
"
