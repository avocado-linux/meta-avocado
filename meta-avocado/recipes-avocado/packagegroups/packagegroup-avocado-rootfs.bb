DESCRIPTION = "Packagegroup for inclusion in  Avocado image"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  packagegroup-core-boot \
  base-files \
  base-passwd \
  netbase \
  avocado-shadow-users \
  avocadoctl \
  btrfs-tools \
  ${VIRTUAL-RUNTIME_base-utils} \
  ${VIRTUAL-RUNTIME_login_manager} \
  ${MACHINE_ESSENTIAL_EXTRA_RDEPENDS} \
"

RDEPENDS:${PN}:append:bootvars-ubootenv = " libubootenv-bin"

RRECOMMENDS:${PN} = "\
  ${VIRTUAL-RUNTIME_base-utils-syslog} \
  ${MACHINE_ESSENTIAL_EXTRA_RRECOMMENDS} \
"
