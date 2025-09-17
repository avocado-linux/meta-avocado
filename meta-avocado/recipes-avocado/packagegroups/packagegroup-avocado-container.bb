DESCRIPTION = "Packagegroup for inclusion in Avocado Container image"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  avocado-sdk-repos \
  avocado-sdk-scripts \
  base-files \
  base-passwd \
  ca-certificates \
  dnf \
  os-release \
  tree \
  usbutils \
"
