DESCRIPTION = "Packagegroup for inclusion in  Avocado image"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  packagegroup-core-boot \
  os-release \
  base-files \
  base-passwd \
  netbase \
  avocadoctl \
  avocado-users \
  btrfs-tools \
  ${@bb.utils.contains('DISTRO_FEATURES','zram','systemd-zram-generator','',d)} \
  ${VIRTUAL-RUNTIME_base-utils} \
  ${VIRTUAL-RUNTIME_login_manager} \
  ${MACHINE_ESSENTIAL_EXTRA_RDEPENDS} \
  packagegroup-avocado-rootfs-modules \
"

RDEPENDS:${PN}:append:bootvars-ubootenv = " libubootenv-bin"

RRECOMMENDS:${PN} = "\
  ${VIRTUAL-RUNTIME_base-utils-syslog} \
  ${MACHINE_ESSENTIAL_EXTRA_RRECOMMENDS} \
"
