DESCRIPTION = "Packagegroup for inclusion in Avocado initramfs image"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = "\
  cryptsetup \
  cryptsetup-var \
  systemd \
  systemd-extra-utils \
  os-release-initrd \
  util-linux \
  util-linux-blkid \
  util-linux-lsblk \
  avocadoctl \
  avocado-users \
  ${@bb.utils.contains('DISTRO_FEATURES','zram','systemd-zram-generator','',d)} \
  packagegroup-avocado-initramfs-modules \
"

RDEPENDS:${PN}:append:bootvars-ubootenv = " libubootenv-bin"
