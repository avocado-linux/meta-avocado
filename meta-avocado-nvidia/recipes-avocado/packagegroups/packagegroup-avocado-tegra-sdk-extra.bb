DESCRIPTION = "Packagegroup for inclusion in extra Avocado SDK extras for tegra"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  nativesdk-packagegroup-cuda-sdk-host \
"
