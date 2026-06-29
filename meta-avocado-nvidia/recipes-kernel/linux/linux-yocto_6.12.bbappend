FILESEXTRAPATHS:prepend := "${THISDIR}/linux-yocto-6.12:"

SRC_URI += " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
"

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc

# Tegra-critical modules pulled into the initramfs via the auto-appended
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

# Tegra hardware modules previously contributed via meta-tegra's unversioned
# MACHINE_ESSENTIAL_EXTRA_RRECOMMENDS in tegra-common.inc. Routed here as
# fully-qualified ${KERNEL_VERSION}-suffixed RDEPENDS so dnf installs this
# kernel's modules instead of NVR-tiebreaking against another kernel in the
# rolling feed. avocado-cli auto-appends this packagegroup whenever the
# rootfs is being installed and this kernel is the lockfile-pinned one.
#
# Same list as linux-jammy-nvidia-tegra_%.bbappend — for modules that are
# Tegra-vendor-only on the linux-yocto 6.6 side, the OOT layer
# (nvidia-kernel-oot) provides the package; for in-tree modules, linux-yocto
# 6.6 provides them directly. Either way, dnf resolves the suffixed name to
# whichever recipe built it.
RDEPENDS:packagegroup-avocado-rootfs-modules:append = " \
    kernel-module-ina3221-${KERNEL_VERSION} \
    kernel-module-lm90-${KERNEL_VERSION} \
    kernel-module-tegra-bpmp-thermal-${KERNEL_VERSION} \
    kernel-module-spi-tegra114-${KERNEL_VERSION} \
    kernel-module-pwm-fan-${KERNEL_VERSION} \
    kernel-module-governor-userspace-${KERNEL_VERSION} \
    kernel-module-ucsi-ccg-${KERNEL_VERSION} \
    kernel-module-pcie-tegra194-${KERNEL_VERSION} \
    kernel-module-phy-tegra194-p2u-${KERNEL_VERSION} \
    kernel-module-nvme-${KERNEL_VERSION} \
    kernel-module-pwm-tegra-${KERNEL_VERSION} \
    kernel-module-tegra-xudc-${KERNEL_VERSION} \
    kernel-module-lz4-${KERNEL_VERSION} \
    kernel-module-lz4-compress-${KERNEL_VERSION} \
    kernel-module-sch-fq-codel-${KERNEL_VERSION} \
"
