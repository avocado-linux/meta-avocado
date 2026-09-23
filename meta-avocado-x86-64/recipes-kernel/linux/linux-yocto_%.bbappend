FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

COMPATIBLE_MACHINE:avocado-x86-64 = "avocado-intel-x86-64-v2|avocado-intel-x86-64-v3|avocado-intel-x86-64-v4"
COMPATIBLE_MACHINE:avocado-amd-x86-64 = "avocado-amd-x86-64-v4"

# Use upstream x86_64 defconfig as base, then layer our .cfg fragments on top
KBUILD_DEFCONFIG:avocado-x86-64 = "x86_64_defconfig"

SRC_URI:append:avocado-x86-64 = " \
    file://avocado-core.cfg \
    file://avocado-extra.cfg \
    file://tpm.cfg \
    file://nvidia-gpu.cfg \
    file://x86-efi.cfg \
"

# amd-x86-64.cfg lives in meta-avocado-amd-x86-64, not this layer's own
# recipes-kernel/linux/files/ - expose that dir the same way
# meta-avocado-nxp's AVOCADO_NXP_KERNEL_FILESDIR does for its relocated
# bbappends, since ${LAYERDIR} is not available at this recipe's parse time.
FILESEXTRAPATHS:prepend:avocado-amd-x86-64 := "${AVOCADO_AMD_X86_64_KERNEL_FILESDIR}:"
SRC_URI:append:avocado-amd-x86-64 = " file://amd-x86-64.cfg"

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
