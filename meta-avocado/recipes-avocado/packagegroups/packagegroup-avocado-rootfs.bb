DESCRIPTION = "Packagegroup for inclusion in  Avocado image"
LICENSE = "Apache-2.0"

PACKAGE_ARCH = "${MACHINE_ARCH}"
inherit packagegroup nospdx
PACKAGES = "${PN}"

# Mirror the VIRTUAL-RUNTIME default that packagegroup-core-boot would have
# set. We inline core-boot's userspace contributions below rather than
# RDEPEND on it (see below for why).
VIRTUAL-RUNTIME_dev_manager ?= "udev"

# Intentionally do NOT RDEPEND on packagegroup-core-boot. core-boot expands
# ${MACHINE_ESSENTIAL_EXTRA_RDEPENDS} and ${MACHINE_ESSENTIAL_EXTRA_RRECOMMENDS}
# into its dep set; on Tegra, the latter contains a long list of UNVERSIONED
# `kernel-module-*` names (`kernel-module-pcie-tegra194`,
# `kernel-module-tegra-xudc`, `kernel-module-pwm-fan`, ...) that dnf NVR-
# tiebreaks across kernels in a multi-kernel feed — pulling 5.15 L4T modules
# into a 6.6 yocto-standard rootfs and dragging the off-kernel
# `kernel-${other_kver}` base in with them. The userspace bits we'd otherwise
# pick up from core-boot (init/dev/login/update-alternatives managers,
# base-utils, base-files, base-passwd, netbase, os-release) are inlined here.
#
# Kernel-versioned content is routed through:
#   - kernel-image-${KERNEL_VERSION}: explicitly installed by avocado-cli at
#     install time using the lockfile-pinned kernel.
#   - packagegroup-avocado-rootfs-modules-${KERNEL_VERSION}: auto-appended by
#     avocado-cli; per-kernel RDEPENDS are set in each kernel bbappend so each
#     kernel's flavor only ships modules that were actually built for it.
#   - packagegroup-avocado-rootfs-modules-oot-${KERNEL_VERSION}: same pattern
#     for OOT modules emitted by nvidia-kernel-oot.
#
# We also drop ${MACHINE_ESSENTIAL_EXTRA_RDEPENDS} from RDEPENDS for the same
# multi-kernel safety reason — on Tegra it carries `nvidia-kernel-oot-base`
# (which only the alt mc 5.15 builds) and unqualified `kernel`/`kernel-image`
# providers. `tegra-firmware`, the one usable item it contributes, comes via
# packagegroup-avocado-tegra-rootfs (whose RDEPENDS pulls
# `tegra-firmware-tegra234`).
#
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

RDEPENDS:${PN} = " \
  os-release \
  base-files \
  base-passwd \
  netbase \
  avocadoctl \
  avocado-users \
  btrfs-tools \
  ${@bb.utils.contains('AVOCADO_VAR_PART_DEV','/dev/mapper/var','cryptsetup-var-udev','',d)} \
  ${@bb.utils.contains('DISTRO_FEATURES','zram','systemd-zram-generator','',d)} \
  ${VIRTUAL-RUNTIME_base-utils} \
  ${VIRTUAL-RUNTIME_init_manager} \
  ${VIRTUAL-RUNTIME_dev_manager} \
  ${VIRTUAL-RUNTIME_update-alternatives} \
  ${VIRTUAL-RUNTIME_login_manager} \
"

RDEPENDS:${PN}:append:bootvars-ubootenv = " libubootenv-bin"

RRECOMMENDS:${PN} = "\
  ${VIRTUAL-RUNTIME_base-utils-syslog} \
"
