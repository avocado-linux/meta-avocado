DESCRIPTION = "Packagegroup for extra inclusions in Avocado Synaptics images"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  ${MACHINE_EXTRA_RRECOMMENDS} \
"
