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
  util-linux-blkid \
  util-linux-lsblk \
  avocadoctl \
  avocado-users \
  ${@bb.utils.contains('DISTRO_FEATURES','zram','systemd-zram-generator','',d)} \
  packagegroup-avocado-initramfs-modules \
"

RDEPENDS:${PN}:append:bootvars-ubootenv = " libubootenv-bin"

# The shell tools initrd units call. Nothing else this packagegroup installs
# provides sed or grep - coreutils ships neither, and busybox is not part of
# it - so an initramfs has them only if something names them. Named here once
# rather than per unit, so every initramfs script can rely on them.
RDEPENDS:${PN} += "sed grep"
