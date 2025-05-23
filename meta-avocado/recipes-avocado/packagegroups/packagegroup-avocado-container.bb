DESCRIPTION = "Packagegroup for inclusion in Avocado Container image"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup

RDEPENDS:${PN} = " \
  busybox \
  base-files \
  base-passwd \
  avocado-sdk \
  dnf \
  os-release \
  ca-certificates \
  avocado-sdk-container-entrypoint \
  gosu \
  shadow \
  glibc-utils \
  sudo \
"

