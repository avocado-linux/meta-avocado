DESCRIPTION = "Packagegroup for inclusion in extra Avocado tegra images"
LICENSE = "Apache-2.0"

inherit packagegroup

RDEPENDS:${PN} = " \
  triton-server \
  triton-client \
  triton-python-backend \
  triton-tensorrt-backend \
"
