DESCRIPTION = "Avocado Hardware in the Loop (HITL) tools"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
    nfs-utils \
"

RDEPENDS:${PN}:class-nativesdk += " \
  nativesdk-ganesha \
"

BBCLASSEXTEND = "nativesdk"
