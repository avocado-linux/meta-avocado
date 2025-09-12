DESCRIPTION = "Packagegroup for Avocado SDK"
LICENSE = "Apache-2.0"

inherit packagegroup
PACKAGES = "${PN}"

SDK_TOOLCHAIN_DEPENDS = " \
  avocado-sdk-bootstrap \
  avocado-sdk-toolchain \
"

SDK_SYSROOT_DEPENDS = " \
"

RDEPENDS:${PN} = " \
  ${SDK_TOOLCHAIN_DEPENDS} \
  ${SDK_SYSROOT_DEPENDS} \
"
