DESCRIPTION = "Packagegroup for Avocado SDK All Metadata packages"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "all_avocadosdk"
inherit packagegroup nospdx
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  ${VIRTUAL-RUNTIME_avocado-sdk-metadata} \
"
