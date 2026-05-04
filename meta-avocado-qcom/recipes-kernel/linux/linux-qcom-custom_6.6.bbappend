FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += " \
    file://avocado-core.cfg \
    file://avocado-extra.cfg \
    file://0001-arm64-dts-qcom-add-Thundercomm-RUBIK-Pi-3-board.patch \
"

KERNEL_CONFIG_FRAGMENTS:append = " ${WORKDIR}/avocado-core.cfg ${WORKDIR}/avocado-extra.cfg"

inherit avocado-kernel-feed
require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc

# Note: upstream qcom_defconfig builds the rubikpi3 storage stack
# (CONFIG_SCSI_UFS_QCOM, CONFIG_PHY_QCOM_QMP) as =y, so they're already in
# the kernel Image — no kernel-module-ufs-qcom / kernel-module-phy-qcom-qmp
# packages need to land in the initramfs.
