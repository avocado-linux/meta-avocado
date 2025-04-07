DESCRIPTION = "Packagegroup for Avocado SDK"
LICENSE = "Apache-2.0"

inherit packagegroup

DEPENDS += "packagegroup-core-standalone-sdk-target target-sdk-provides-dummy"

RDEPENDS:${PN} = " \
  avocado-sdk-toolchain \
"
