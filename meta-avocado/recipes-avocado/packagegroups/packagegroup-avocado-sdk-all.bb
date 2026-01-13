DESCRIPTION = "Packagegroup for Avocado SDK All Metadata packages"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "all_avocadosdk"
inherit packagegroup
PACKAGES = "${PN}"

do_compile[depends] += "avocado-core:do_build"
do_compile[depends] += "avocado-stone:do_build"
do_compile[depends] += "avocado-pkg-extra:do_build"

RDEPENDS:${PN} = " \
  ${VIRTUAL-RUNTIME_avocado-sdk-metadata} \
"
