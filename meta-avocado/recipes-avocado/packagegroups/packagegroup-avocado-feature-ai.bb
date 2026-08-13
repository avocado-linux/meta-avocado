DESCRIPTION = "Packagegroup for Avocado AI feature group"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  ${@bb.utils.contains('MACHINE_FEATURES', 'deepx', "${DEEPX_PACKAGES}", '', d)} \
"

DEEPX_PACKAGES = " \
  dx-driver \
  dx-rt \
  dx-stream \
  dx-stream-sample \
"
