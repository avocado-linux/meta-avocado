# Everything every Avocado Jetson kernel gets, regardless of which tree it
# comes from.
#
# Four recipes require this, in two families:
#
#   linux-yocto                  linux-noble-nvidia-tegra        (default mcs)
#   linux-yocto-rt               linux-noble-nvidia-tegra-rt     (PREEMPT_RT mcs)
#
# A `require` does NOT carry the required recipe's bbappends -- bbappends match
# on the filename being parsed, and each of the four is a different filename
# with a different PN. So the RT siblings cannot inherit any of this from the
# stock ones; without a shared .inc they would build with none of the avocado
# cfg fragments, no dm-verity/fTPM support and none of the feed classes. Same
# reason meta-avocado-qcom/recipes-kernel/linux/avocado-linux-qcom.inc exists.
#
# What stays OUT of here, in the per-family incs:
#   - FILESEXTRAPATHS, because each family's avocado-extra.cfg is its own file
#     with genuinely different content (the linux-yocto one carries
#     CONFIG_PWM_GPIO, the noble one carries the MIC-73x/71x carrier NICs,
#     pstore and joydev).
#   - the linux-yocto spi-tegra114 patch, which does not apply to the 6.8 L4T
#     tree, and the noble scmversion suppression, which the linux-yocto tree
#     does not need.

# Avocado's own kernel config. The filenames are the same in both families;
# which directory they resolve out of is set by the per-family .inc.
SRC_URI += " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
"

# dm-crypt/dm-verity capability (shared fragments) + the OP-TEE fTPM driver.
# Unconditional: see avocado-security-kernel.inc for why capability is not
# gated on a DISTRO_FEATURE. files/ftpm.cfg is shared by all four kernels.
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
# feed -- which now holds four kernels per machine, not two.
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
# For modules that are Tegra-vendor-only on the linux-yocto side, the OOT layer
# (nvidia-kernel-oot) provides the package; for in-tree modules, linux-yocto
# provides them directly. Either way, dnf resolves the suffixed name to
# whichever recipe built it.
#
# :append, not =, so the zram entry avocado-kernel-modules-packagegroup.inc
# contributes survives. The noble bbappend used to re-assign this list and
# hand-carry its own copy of the zram conditional; that is what let the two
# families' copies drift apart in the first place.
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
# ones. avocado-cli auto-appends packagegroup-avocado-{rootfs,initramfs}-
# modules-${KV} but has no native awareness of the OOT siblings emitted from
# nvidia-kernel-oot_%.bbappend, so without this hard dep the initramfs gets no
# updates/ directory at all -- none of the OOT modules.
#
# On tegra264 that is fatal to boot: the in-tree pcie-tegra194 above does NOT
# match the Thor PCIe nodes (compatible = "nvidia,tegra264-pcie") and binds
# nothing, so there is no PCIe bus, nvme/nvme-core load with no device to
# attach to, and avocado-tegra-init fails with
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
# This used to live only in the noble bbappend, on the assumption that
# linux-yocto 6.18 had no nvidia-kernel-oot build and therefore no OOT sibling
# to depend on. That stopped being true, both stock bbappends ended up with
# their own copy, and now all four kernels get it from here.
#
# Use the unqualified name (not ...-${KERNEL_VERSION}): KERNEL_VERSION is
# computed from the kernel build dir at do_compile time, so referencing it
# inside an RDEPENDS string gets the literal "None" at parse-time RDEPENDS
# resolution (KERNEL_MODULE_PACKAGE_SUFFIX is the late-bound form, but
# kernel-module-split.bbclass only handles that for kernel-module-* names via
# do_split_packages -- packagegroups have no equivalent magic). The unqualified
# RPROVIDES on the OOT packagegroup makes this resolve cleanly.
#
# CAVEAT, and it got wider when the RT mcs landed: this hop is resolved by
# dnf's NVR tie-break, so with four kernels in the feed there are four
# providers of the bare name and the newest wins rather than this kernel's.
# nvidia-kernel-oot_%.bbappend calls that out as the deliberate install-latest
# behavior for the unqualified OOT virtuals (pin with avocado.kernel.version),
# and nvidia-kernel-oot-base's own RDEPENDS on TEGRA_OOT_BASE_DRIVERS is
# unqualified upstream too. Nothing here makes it worse per kernel, but the odds
# of landing on a foreign kernel's OOT set go from one-in-two to three-in-four.
RDEPENDS:packagegroup-avocado-initramfs-modules:append = " packagegroup-avocado-initramfs-modules-oot"
RDEPENDS:packagegroup-avocado-rootfs-modules:append = " packagegroup-avocado-rootfs-modules-oot"
