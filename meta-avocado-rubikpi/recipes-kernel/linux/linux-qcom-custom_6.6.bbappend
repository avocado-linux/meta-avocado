LIC_FILES_CHKSUM = "file://COPYING;md5=6bc538ed5bd9a7fc9398086aedcd7e46"

SRC_URI = "git://git@github.com/rubikpi-ai/linux;protocol=https;nobranch=1 \
           ${@bb.utils.contains('DISTRO_FEATURES', 'selinux', ' file://selinux.cfg', '', d)} \
           ${@bb.utils.contains('DISTRO_FEATURES', 'selinux', ' file://selinux_debug.cfg', '', d)} \
           ${@bb.utils.contains('DISTRO_FEATURES', 'smack', ' file://smack.cfg', '', d)} \
           ${@bb.utils.contains('DISTRO_FEATURES', 'smack', ' file://smack_debug.cfg', '', d)} \
           file://0001-QCLINUX-Add-support-to-compile-msm_display.ko.patch \
           file://0002-PENDING-misc-fastrpc-Return-on-argument-copy-failure.patch \
           file://0003-QCLINUX-arm64-dts-qcom-Add-board-id-and-msm-id-for-R.patch"

SRCREV = "8c1599030840bcca335c12a08c7485a885345d62"

S = "${WORKDIR}/git"

do_configure:append() {
    kernel_conf_variable BTRFS_FS y
    kernel_conf_variable EROFS_FS y
    kernel_conf_variable EROFS_FS_ZIP y
    kernel_conf_variable SQUASHFS y
    kernel_conf_variable SQUASHFS_ZSTD y
    kernel_conf_variable LOCALVERSION ""
    kernel_conf_variable LOCALVERSION_AUTO n
    kernel_conf_variable AUDIT n
    kernel_conf_variable USB_DWC3 n
    kernel_conf_variable CRYPTO_LZ4 m
    kernel_conf_variable ZRAM m
    oe_runmake -C ${S} O=${B} savedefconfig && cp ${B}/defconfig ${WORKDIR}/defconfig.saved
}

KERNEL_CONFIG_FRAGMENTS:append = " ${S}/arch/arm64/configs/rubikpi3.config"

# Rename kernel-devsrc to include KERNEL_VERSION so multiple kernel versions
# can coexist in a rolling feed without colliding on the unversioned package
# name. Publish both the unqualified and the versioned virtual Provides so
# existing callers (e.g. `packagegroup-avocado-sdk-extra.bb` listing
# `kernel-devsrc`) keep working, and explicit pinners can target
# `kernel-devsrc-{{ avocado.kernel.version }}` via interpolation.
PKG:${KERNEL_PACKAGE_NAME}-devsrc = "${KERNEL_PACKAGE_NAME}-devsrc-${KERNEL_VERSION}"
RPROVIDES:${KERNEL_PACKAGE_NAME}-devsrc += "kernel-devsrc kernel-devsrc-${KERNEL_VERSION}"

# Same multi-kernel feed-collision rationale as kernel-devsrc above. The
# kernel-devicetree package emitted by kernel-devicetree.bbclass is not auto-
# renamed by kernel.bbclass, so two kernels' RPMs would land on the same NAME
# and dnf would NVR-tiebreak. Fully-qualify it so avocado-cli's `-${KERNEL_VERSION}`
# auto-suffix resolves to the resolver-pinned kernel.
PKG:${KERNEL_PACKAGE_NAME}-devicetree = "${KERNEL_PACKAGE_NAME}-devicetree-${KERNEL_VERSION}"
RPROVIDES:${KERNEL_PACKAGE_NAME}-devicetree += "kernel-devicetree kernel-devicetree-${KERNEL_VERSION}"

# Publish a well-known virtual that avocado-cli's kernel resolver queries
# with `dnf repoquery --whatprovides 'avocado-kernel-*' --provides`. Encodes
# KERNEL_VERSION in the Provide name so the resolver can enumerate every
# kernel available in the feed without fishing through package NAMEs or
# relying on kernel.bbclass's (nonexistent) unqualified `kernel` Provide.
RPROVIDES:${KERNEL_PACKAGE_NAME}-base += "avocado-kernel-${KERNEL_VERSION}"

require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
