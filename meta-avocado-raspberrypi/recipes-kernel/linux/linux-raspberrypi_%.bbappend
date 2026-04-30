FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
"

SRC_URI:append:reterminal = " file://reterminal.cfg"
SRC_URI:append:reterminal-dm = " file://reterminal.cfg"

require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc

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
