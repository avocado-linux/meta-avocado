FILESEXTRAPATHS:prepend := "${THISDIR}/linux-yocto-6.18:${THISDIR}/files:"

SRC_URI += " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
"

# spi-tegra114 drops a software-held chip select on the next spi_message, which
# breaks any driver that builds one transaction out of several messages with
# cs_change (tpm_tis_spi, cros_ec_spi, mmc_spi, ad_sigma_delta, ...). On Thor
# this is why a discrete SPI TPM never binds: the TIS data phase reads back as
# zeros and tpm_tis_core_init() gives up with -ENODEV before tpm_chip_start().
# See the patch header for the userspace reproduction that isolates it from the
# TPM driver.
SRC_URI += " file://0001-spi-tegra114-keep-software-CS-across-a-multi-message-.patch"

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
