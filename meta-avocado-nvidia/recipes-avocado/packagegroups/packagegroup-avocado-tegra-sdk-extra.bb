DESCRIPTION = "Packagegroup for inclusion in extra Avocado SDK extras for tegra"
LICENSE = "Apache-2.0"

inherit packagegroup

RDEPENDS:${PN} = " \
  nativesdk-packagegroup-cuda-sdk-host \
"
