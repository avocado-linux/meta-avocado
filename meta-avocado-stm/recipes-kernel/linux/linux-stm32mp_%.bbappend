FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = " \
    file://avocado-core.cfg \
    file://avocado-extra.cfg \
"

# linux-stm32mp.inc uses a custom merge_config-driven mechanism (not the
# standard kernel.bbclass SRC_URI-auto-merge) so .cfg fragments must be
# explicitly appended to KERNEL_CONFIG_FRAGMENTS or they're staged into
# WORKDIR but never merged into .config.
KERNEL_CONFIG_FRAGMENTS:append = " ${WORKDIR}/avocado-core.cfg ${WORKDIR}/avocado-extra.cfg"

inherit avocado-kernel-feed
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
