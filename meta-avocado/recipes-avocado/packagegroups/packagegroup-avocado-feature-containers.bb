DESCRIPTION = "Packagegroup for Avocado containers feature group"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  ${@bb.utils.contains('DISTRO_FEATURES', 'virtualization', "${CONTAINER_PACKAGES}", '', d)} \
"

CONTAINER_PACKAGES = " \
  docker \
  podman \
  podman-compose \
  k3s \
"
