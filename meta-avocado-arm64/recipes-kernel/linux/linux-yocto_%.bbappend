FILESEXTRAPATHS:prepend:arm64-uefi := "${THISDIR}/files:"

COMPATIBLE_MACHINE:arm64-uefi = "avocado-arm64-uefi-v9"

# Use the upstream arm64 defconfig as base, then layer our .cfg fragments on top.
KBUILD_DEFCONFIG:arm64-uefi = "defconfig"
# The in-tree defconfig is in savedefconfig form: it omits every option left at
# its Kconfig default. kernel-yocto merges a defconfig with allnoconfig unless
# told otherwise, which turns all of those off (USB_SUPPORT, and with it USB
# storage and xhci; mlx5 and MT7925 via their default-y vendor menus).
KCONFIG_MODE:arm64-uefi = "alldefconfig"

SRC_URI:append:arm64-uefi = " \
    file://avocado-core.cfg \
    file://avocado-extra.cfg \
    file://arm64-uefi.cfg \
    file://0001-cpufreq-CPPC-enable-CPPC-when-a-policy-starts.patch \
"

# dm-crypt/dm-verity capability; see the include for why it is unconditional.
require recipes-kernel/linux/avocado-security-kernel.inc

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc

# Root and /var can live on NVMe; nvme is =m in the arm64 defconfig.
RDEPENDS:packagegroup-avocado-initramfs-modules:append:arm64-uefi = " \
    kernel-module-nvme-${KERNEL_VERSION} \
"
