DESCRIPTION = "Avocado Hardware in the Loop (HITL) tools"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
PACKAGES = "${PN}"
inherit packagegroup nospdx

RDEPENDS:${PN} = " \
    nfs-utils \
"
