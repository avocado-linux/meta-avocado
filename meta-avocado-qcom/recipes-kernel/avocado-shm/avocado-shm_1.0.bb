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

# Every qcom machine whose runtime carries the inter-VM demo. Nothing in the
# driver is board-specific -- it binds on compatible = "avocado,shm" and maps
# whatever its memory-region phandle points at -- so this list is the consumer
# set, not a hardware constraint.
COMPATIBLE_MACHINE = "(q911|rubikpi3|rb3gen2)"

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

# Ported here from meta-avocado-innodisk, where it was originally written for
# the EXMP-Q911. It is in meta-avocado-qcom rather than the innodisk layer
# because all three consumers -- q911, rubikpi3, rb3gen2 -- build with this
# layer, and rb3gen2 cannot see the innodisk one at all: its `vmm` extension
# failed with "No match for argument: kernel-module-avocado-shm".
#
# Nothing in it is actually qcom-specific either. If a non-qcom board ever
# needs the demo, this moves to core rather than being copied again.
#
# NOTE for the q911: its build pulls meta-avocado as a pinned kas repo, so it
# keeps using the innodisk copy until that pin advances past this commit. The
# innodisk recipe is superseded, not yet removed -- delete it in the same
# change that repins, or the q911 briefly has two providers of the same PN.
