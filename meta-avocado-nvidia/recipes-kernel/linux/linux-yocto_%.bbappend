FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
  file://0001-mailbox-tegra-hsp-backport-L4T-shared-interrupt-mapping.patch \
  file://0002-mailbox-tegra-hsp-enable-per-mailbox-empty-interrupt.patch \
"

# Rename kernel-devsrc to include KERNEL_VERSION so multiple kernel versions
# can coexist in a rolling feed without colliding on the unversioned package
# name. Publish both the unqualified and the versioned virtual Provides so
# existing callers (e.g. `packagegroup-avocado-sdk-extra.bb` listing
# `kernel-devsrc`) keep working, and explicit pinners can target
# `kernel-devsrc-{{ avocado.kernel.version }}` via interpolation.
PKG:${KERNEL_PACKAGE_NAME}-devsrc = "${KERNEL_PACKAGE_NAME}-devsrc-${KERNEL_VERSION}"
RPROVIDES:${KERNEL_PACKAGE_NAME}-devsrc += "kernel-devsrc kernel-devsrc-${KERNEL_VERSION}"

# Publish a well-known virtual that avocado-cli's kernel resolver queries
# with `dnf repoquery --whatprovides 'avocado-kernel-*' --provides`. Encodes
# KERNEL_VERSION in the Provide name so the resolver can enumerate every
# kernel available in the feed without fishing through package NAMEs or
# relying on kernel.bbclass's (nonexistent) unqualified `kernel` Provide.
RPROVIDES:${KERNEL_PACKAGE_NAME}-base += "avocado-kernel-${KERNEL_VERSION}"

require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc

# Tegra-critical modules pulled into rootfs/initramfs via the auto-appended
# per-kernel packagegroup. nvme drives root-fs storage on Jetson; the
# pcie-tegra194 / phy-tegra194-p2u pair brings the PCIe controller up so the
# nvme controller is reachable; tegra-xudc lets the USB device-controller
# probe for DFU/recovery. Versioned with ${KERNEL_VERSION} so dnf resolves to
# this kernel's module RPMs rather than NVR-tie-breaking across a multi-kernel
# feed.
RDEPENDS:packagegroup-avocado-initramfs-modules:append = " \
    kernel-module-nvme-${KERNEL_VERSION} \
    kernel-module-pcie-tegra194-${KERNEL_VERSION} \
    kernel-module-phy-tegra194-p2u-${KERNEL_VERSION} \
    kernel-module-tegra-xudc-${KERNEL_VERSION} \
"
