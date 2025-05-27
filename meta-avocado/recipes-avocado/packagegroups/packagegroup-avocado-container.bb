DESCRIPTION = "Packagegroup for inclusion in Avocado Container image"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  os-release \
  busybox \
  base-files \
  base-passwd \
  dnf \
  avocado-sdk-repos \
  avocado-sdk-scripts \
  ca-certificates \
"

