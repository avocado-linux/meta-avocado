FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

COMPATIBLE_MACHINE:avocado-x86-64 = "avocado-intel-x86-64-v2|avocado-intel-x86-64-v3|avocado-intel-x86-64-v4"

# Use upstream x86_64 defconfig as base, then layer our .cfg fragments on top
KBUILD_DEFCONFIG:avocado-x86-64 = "x86_64_defconfig"

SRC_URI:append:avocado-x86-64 = " \
    file://avocado-core.cfg \
    file://avocado-extra.cfg \
    file://tpm.cfg \
    file://nvidia-gpu.cfg \
    file://x86-efi.cfg \
"

inherit avocado-kernel-feed
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
