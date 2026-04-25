# Shared per-kernel rootfs/initramfs module packagegroup emission.
#
# Included from every non-tegra kernel bbappend. Produces two subpackages
# per kernel build, renamed at packaging time to include KERNEL_VERSION:
#   - packagegroup-avocado-rootfs-modules-${KERNEL_VERSION}
#   - packagegroup-avocado-initramfs-modules-${KERNEL_VERSION}
#
# avocado-cli auto-appends the matching variant at install time (keyed on
# whether avocado-pkg-rootfs / avocado-pkg-initramfs is in the effective
# package list and which kernel is pinned in the lockfile), so transitive
# module pulls resolve to this kernel's modules rather than dnf's NVR
# tie-break across the feed. Package names are machine-agnostic — each
# target publishes to its own repo stream, so contents differ per feed while
# names stay uniform.
#
# Platforms with rootfs/initramfs-critical modules append them with
# `RDEPENDS:packagegroup-avocado-{rootfs,initramfs}-modules:append` in their
# own bbappend. Module names must include `-${KERNEL_VERSION}` so they
# resolve to this specific kernel's packages.

PACKAGES:append = " packagegroup-avocado-rootfs-modules packagegroup-avocado-initramfs-modules"
PKG:packagegroup-avocado-rootfs-modules = "packagegroup-avocado-rootfs-modules-${KERNEL_VERSION}"
PKG:packagegroup-avocado-initramfs-modules = "packagegroup-avocado-initramfs-modules-${KERNEL_VERSION}"
ALLOW_EMPTY:packagegroup-avocado-rootfs-modules = "1"
ALLOW_EMPTY:packagegroup-avocado-initramfs-modules = "1"
FILES:packagegroup-avocado-rootfs-modules = ""
FILES:packagegroup-avocado-initramfs-modules = ""
SUMMARY:packagegroup-avocado-rootfs-modules = "Kernel modules pulled into the Avocado rootfs for kernel ${KERNEL_VERSION}"
SUMMARY:packagegroup-avocado-initramfs-modules = "Kernel modules pulled into the Avocado initramfs for kernel ${KERNEL_VERSION}"

# Publish an unqualified Provide alongside the versioned PKG NAME so the
# kernel-agnostic packagegroup-avocado-{rootfs,initramfs} packagegroups can
# RDEPEND on `packagegroup-avocado-{rootfs,initramfs}-modules` without
# interpolating KERNEL_VERSION at their own parse time — dnf picks the
# matching provider at install. In per-target repo streams there's exactly
# one kernel (one provider); in multi-kernel feeds dnf NVR-tiebreaks to
# latest. avocado-cli's auto-append still installs the specific pinned
# kver by exact NAME on top of that for deterministic rootfs/initramfs
# sysroot composition.
RPROVIDES:packagegroup-avocado-rootfs-modules = "packagegroup-avocado-rootfs-modules"
RPROVIDES:packagegroup-avocado-initramfs-modules = "packagegroup-avocado-initramfs-modules"

RDEPENDS:packagegroup-avocado-rootfs-modules = " \
    ${@bb.utils.contains('DISTRO_FEATURES','zram','kernel-module-zram-${KERNEL_VERSION}','',d)} \
"
RDEPENDS:packagegroup-avocado-initramfs-modules = " \
    ${@bb.utils.contains('DISTRO_FEATURES','zram','kernel-module-zram-${KERNEL_VERSION}','',d)} \
"
