DESCRIPTION = "Avocado SDK Target Sysroot"
LICENSE = "Apache-2.0"

PV = "${SDK_VERSION}"
PACKAGE_ARCH = "${MACHINE_ARCH}"
PACKAGES = "${PN}"
inherit packagegroup

RDEPENDS:${PN} = "packagegroup-core-standalone-sdk-target"

