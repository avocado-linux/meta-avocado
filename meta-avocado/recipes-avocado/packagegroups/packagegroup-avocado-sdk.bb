DESCRIPTION = "Packagegroup for Avocado SDK"
LICENSE = "Apache-2.0"

inherit packagegroup

RDEPENDS:${PN} = " \
  avocado-sdk-toolchain \
"
