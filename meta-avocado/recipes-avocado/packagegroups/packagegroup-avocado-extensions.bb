DESCRIPTION = "Packagegroup for Avocado extensions"
LICENSE = "Apache-2.0"

inherit packagegroup

RDEPENDS:${PN} = " \
  avocado-extension-debug-tweaks \
"
