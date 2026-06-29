# avocado-kernel-modules-packagegroup.inc
#
# Per-kernel rootfs/initramfs module packagegroups.  avocado-cli auto-appends
# these at install time (keyed on whether avocado-pkg-rootfs / avocado-pkg-
# initramfs is in the effective package list and which kernel is pinned in the
# lockfile), so transitive module pulls resolve to this kernel's modules rather
# than dnf's NVR tie-break across the feed.
#
# Included by every kernel bbappend. Each bbappend then appends its own
# RDEPENDS for kernel-specific modules (e.g. tegra initramfs drivers).

PACKAGES:append = " packagegroup-avocado-rootfs-modules packagegroup-avocado-initramfs-modules"
PKG:packagegroup-avocado-rootfs-modules = "packagegroup-avocado-rootfs-modules-${KERNEL_VERSION}"
PKG:packagegroup-avocado-initramfs-modules = "packagegroup-avocado-initramfs-modules-${KERNEL_VERSION}"
ALLOW_EMPTY:packagegroup-avocado-rootfs-modules = "1"
ALLOW_EMPTY:packagegroup-avocado-initramfs-modules = "1"
FILES:packagegroup-avocado-rootfs-modules = ""
FILES:packagegroup-avocado-initramfs-modules = ""
SUMMARY:packagegroup-avocado-rootfs-modules = "Kernel modules pulled into the Avocado rootfs for kernel ${KERNEL_VERSION}"
SUMMARY:packagegroup-avocado-initramfs-modules = "Kernel modules pulled into the Avocado initramfs for kernel ${KERNEL_VERSION}"

# Publish both unqualified and versioned Provides so existing callers work and
# explicit pinners can target the versioned name.
RPROVIDES:packagegroup-avocado-rootfs-modules = "packagegroup-avocado-rootfs-modules"
RPROVIDES:packagegroup-avocado-initramfs-modules = "packagegroup-avocado-initramfs-modules"

RDEPENDS:packagegroup-avocado-rootfs-modules = " \
    ${@bb.utils.contains('DISTRO_FEATURES','zram','kernel-module-zram-${KERNEL_VERSION}','',d)} \
"
