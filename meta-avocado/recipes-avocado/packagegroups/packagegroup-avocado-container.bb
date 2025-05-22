DESCRIPTION = "Packagegroup for inclusion in Avocado Container image"
LICENSE = "Apache-2.0"

inherit packagegroup

RDEPENDS:${PN} = " \
  busybox \
  base-files \
  base-passwd \
  avocado-sdk \
  dnf \
  os-release \
  ca-certificates \
"

