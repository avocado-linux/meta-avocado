FILESEXTRAPATHS:prepend := "${THISDIR}/linux-yocto-6.18:${THISDIR}/files:"

SRC_URI += " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
"

# dm-crypt/dm-verity capability (shared fragments) + the OP-TEE fTPM driver.
# Unconditional: see avocado-security-kernel.inc for why capability is not
# gated on a DISTRO_FEATURE. files/ftpm.cfg is shared by both Jetson kernels.
require recipes-kernel/linux/avocado-security-kernel.inc
SRC_URI += " file://ftpm.cfg"

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
    kernel-module-tpm-ftpm-tee-${KERNEL_VERSION} \
    kernel-module-dm-mod-${KERNEL_VERSION} \
    kernel-module-dm-crypt-${KERNEL_VERSION} \
"

# Tegra hardware modules previously contributed via meta-tegra's unversioned
# MACHINE_ESSENTIAL_EXTRA_RRECOMMENDS in tegra-common.inc. Routed here as
# fully-qualified ${KERNEL_VERSION}-suffixed RDEPENDS so dnf installs this
# kernel's modules instead of NVR-tiebreaking against another kernel in the
# rolling feed. avocado-cli auto-appends this packagegroup whenever the
# rootfs is being installed and this kernel is the lockfile-pinned one.
#
# Same list as linux-noble-nvidia-tegra_%.bbappend — for modules that are
# Tegra-vendor-only on the linux-yocto side, the OOT layer (nvidia-kernel-oot)
# provides the package; for in-tree modules, linux-yocto provides them
# directly. Either way, dnf resolves the suffixed name to whichever recipe
# built it.
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

# Pull the OOT initramfs/rootfs packagegroups in alongside the kernel-owned
# ones, exactly as linux-noble-nvidia-tegra_%.bbappend does.
#
# This used to be noble-only on the assumption that linux-yocto 6.18 had no
# nvidia-kernel-oot build and therefore no OOT sibling to depend on. That is no
# longer true: nvidia-kernel-oot now builds against this kernel too, and the
# feed carries packagegroup-avocado-{initramfs,rootfs}-modules-oot-${KV} for it.
#
# Without this, the initramfs gets no updates/ directory at all -- none of the
# OOT modules. On tegra264 that is fatal to boot: the in-tree pcie-tegra194
# above does NOT match the Thor PCIe nodes (compatible = "nvidia,tegra264-pcie")
# and binds nothing, so there is no PCIe bus, nvme/nvme-core load with no device
# to attach to, and avocado-tegra-init fails with
#
#   [FAIL] root= fallback empty; scanning all disks for APP partitions
#   Error: could not locate APP rootfs partition
#
# taking initrd-switch-root.service down with it and dropping to the initramfs
# emergency shell. Observed on an AGX Thor on the first upstream-kernel boot:
# lsblk showed only zram0, and pcie_tegra194 was loaded with "Used by 0".
#
# See nvidia-kernel-oot_%.bbappend for why Thor needs the whole
# nvidia-kernel-oot-base set here and not just pcie-tegra264 (the controller's
# DT node needs OOT clock/reset/IOMMU providers or its probe -EPROBE_DEFERs
# forever).
#
# Unqualified name on purpose -- see the same note in the noble bbappend:
# KERNEL_VERSION is not bound at parse-time RDEPENDS resolution, and the OOT
# packagegroup publishes an unqualified RPROVIDES for exactly this.
RDEPENDS:packagegroup-avocado-initramfs-modules:append = " packagegroup-avocado-initramfs-modules-oot"
RDEPENDS:packagegroup-avocado-rootfs-modules:append = " packagegroup-avocado-rootfs-modules-oot"
