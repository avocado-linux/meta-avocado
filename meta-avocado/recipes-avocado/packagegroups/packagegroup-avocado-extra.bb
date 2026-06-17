DESCRIPTION = "Packagegroup for Avocado extra"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup
PACKAGES = "${PN}"

RDEPENDS:${PN} = " \
  avocado-hitl \
  avocado-img-bootfiles \
  avocado-img-initramfs \
  avocado-img-rootfs \
  avocado-img-var \
  avocado-pkg-rootfs \
  avocado-pkg-initramfs \
  linux-firmware \
  phytool \
  qemu-user-static \
  qemu-user-static-binfmt \
  qemu-guest-agent \
"

RDEPENDS:${PN} += "${@' '.join('packagegroup-avocado-feature-' + g for g in (d.getVar('AVOCADO_FEATURE_GROUPS') or '').split())}"
