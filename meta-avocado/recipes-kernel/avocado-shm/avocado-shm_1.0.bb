SUMMARY = "Cacheable userspace mapping of one reserved memory region"
DESCRIPTION = "Guest-side driver for the inter-VM shared window. Hands out \
exactly the region named by its device-tree memory-region phandle, mapped \
write-back cacheable -- which an ivshmem PCI BAR cannot be on arm64."
LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/GPL-2.0-only;md5=801f80980d171dd6425610833a22dbe6"

inherit module

SRC_URI = " \
    file://Makefile \
    file://avocado-shm.c \
"

S = "${UNPACKDIR}"

# No COMPATIBLE_MACHINE: nothing in the driver is board-specific -- it binds on
# compatible = "avocado,shm" and maps whatever its memory-region phandle points
# at. A machine builds it only when a packagegroup names
# kernel-module-avocado-shm, and each multi-kernel machine also lists it in
# AVOCADO_MULTIKERNEL_MC_RECIPES so every kernel gets a matching module.

# Built by Yocto rather than through sdk.compile.<name>, and the reason is
# vermagic. The SDK route (see extensions/ext-kmod-v4l2loopback for the shape)
# builds against the kernel-devsrc package, and there is exactly one of those
# in this feed -- the STOCK kernel, 6.18.37. The guests run the host's Image,
# which is the RT kernel, 6.18.37-rt. A module carrying stock vermagic is
# rejected on load. Building here instead means the module is produced once per
# kernel by the multiconfig, so the RT variant exists and matches by
# construction.
#
# The generic fix would be to publish kernel-devsrc per kernel version the way
# kernel-module-* packages already are, which would make the SDK route work for
# multi-kernel targets too.

# Written for the Innodisk EXMP-Q911, then carried in meta-avocado-qcom for
# q911, rubikpi3 and rb3gen2. In core since Jetson became the first non-qcom
# consumer.
#
# NOTE for the q911: its build pulls meta-avocado as a pinned kas repo, so it
# keeps using the innodisk copy until that pin advances past this commit. The
# innodisk recipe is superseded, not yet removed -- delete it in the same
# change that repins, or the q911 briefly has two providers of the same PN.
