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
"

# NOTE: Intentionally NO unqualified `packagegroup-avocado-rootfs-modules`
# RDEPENDS here. In a multi-kernel feed, several kernels each Provide that
# unqualified virtual (via avocado-kernel-modules-packagegroup.inc) and dnf
# NVR-tiebreaks across them — non-deterministically pulling in a kernel
# generation other than the one targeted for this rootfs. The fully-qualified
# packagegroup-avocado-rootfs-modules-${KERNEL_VERSION} is the only safe
# reference. avocado-cli auto-appends it from the lockfile pin at install
# time, so cli-driven flows (avocado-pkg-rootfs in an extension sysroot) get
# the right modules without any indirection here.
#
# Yocto image builds (avocado-image-rootfs.bb) need the version-qualified
# packagegroup added explicitly via IMAGE_INSTALL or ROOTFS_IMAGE_EXTRA_INSTALL
# — they no longer get it implicitly via this packagegroup. Without that
# explicit add, the image will boot but ship without rootfs modules.

RDEPENDS:${PN}:append:bootvars-ubootenv = " libubootenv-bin"

RRECOMMENDS:${PN} = "\
  ${VIRTUAL-RUNTIME_base-utils-syslog} \
  ${MACHINE_ESSENTIAL_EXTRA_RRECOMMENDS} \
"
