FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI_SHARED = " \
  file://dm-verity.cfg.in \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
"
SRC_URI:append:avocado-qemux86-64 = " \
  ${SRC_URI_SHARED} \
  file://tpm.cfg \
"

SRC_URI:append:avocado-qemuarm64 = " \
  ${SRC_URI_SHARED} \
  file://mmc.cfg \
  file://ftpm.cfg \
"

YOCTO_BUILD_DIR = "${TOPDIR}"

# Rename kernel-devsrc to include KERNEL_VERSION so multiple kernel versions
# can coexist in a rolling feed without colliding on the unversioned package
# name. Publish both the unqualified and the versioned virtual Provides so
# existing callers (e.g. `packagegroup-avocado-sdk-extra.bb` listing
# `kernel-devsrc`) keep working, and explicit pinners can target
# `kernel-devsrc-{{ avocado.kernel.version }}` via interpolation.
PKG:${KERNEL_PACKAGE_NAME}-devsrc = "${KERNEL_PACKAGE_NAME}-devsrc-${KERNEL_VERSION}"
RPROVIDES:${KERNEL_PACKAGE_NAME}-devsrc += "kernel-devsrc kernel-devsrc-${KERNEL_VERSION}"

# Publish a well-known virtual that avocado-cli's kernel resolver queries
# with `dnf repoquery --whatprovides 'avocado-kernel-*' --provides`. Encodes
# KERNEL_VERSION in the Provide name so the resolver can enumerate every
# kernel available in the feed without fishing through package NAMEs or
# relying on kernel.bbclass's (nonexistent) unqualified `kernel` Provide.
RPROVIDES:${KERNEL_PACKAGE_NAME}-base += "avocado-kernel-${KERNEL_VERSION}"

require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc
