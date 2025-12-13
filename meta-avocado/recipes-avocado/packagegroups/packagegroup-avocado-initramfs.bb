DESCRIPTION = "Packagegroup for inclusion in Avocado initramfs image"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = "\
  cryptsetup \
  systemd \
  systemd-extra-utils \
  os-release-initrd \
  util-linux \
  avocadoctl \
  avocado-users \
  ${@bb.utils.contains('DISTRO_FEATURES','zram','systemd-zram-generator','',d)} \
"

RDEPENDS:${PN}:append:bootvars-ubootenv = " libubootenv-bin"
