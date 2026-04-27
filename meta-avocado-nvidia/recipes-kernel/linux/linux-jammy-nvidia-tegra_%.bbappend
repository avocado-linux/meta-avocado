FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append = " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
"

# Disable git-SHA scmversion suffix on KERNEL_VERSION. Two layers add the
# suffix:
#   1. OE's upstream set_scmversion postfunc, gated by SCMVERSION="y" — this
#      also controls whether localversion_auto.cfg gets merged into the kernel
#      config (enabling CONFIG_LOCALVERSION_AUTO).
#   2. Kbuild's own scripts/setlocalversion, which detects .git in ${S} and
#      appends a short SHA whenever CONFIG_LOCALVERSION_AUTO=y — and the abbrev
#      length depends on repo object count, so shallow vs full clones diverge.
# Neither the SHA output nor the abbrev length is captured as a task vardep, so
# sstate restore across environments can mix scmversions between kernel and OOT
# module builds, leaving shim RDEPENDS pointing at a kernel name that nothing
# provides. SRCREV is pinned, so no version info is lost.
SCMVERSION = "n"
# SCMVERSION="n" only prevents the kernel-yocto class from calling its own
# set_scmversion (which is gated on SCMVERSION="y"). Kbuild's
# scripts/setlocalversion is a separate path: it detects .git in ${S} and
# appends +g<sha> independently. Creating an empty .scmversion before compile
# causes setlocalversion to cat the file and return immediately without a git
# lookup, suppressing the suffix at the Kbuild level too.
do_kernel_configme:append() {
    : > ${S}/.scmversion
}

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

# Emit per-kernel rootfs/initramfs module packagegroups. avocado-cli auto-
# appends these at install time (keyed on whether avocado-pkg-rootfs /
# avocado-pkg-initramfs is in the effective package list and which kernel is
# pinned in the lockfile), so transitive module pulls resolve to this
# kernel's modules rather than dnf's NVR tie-break across the feed. Package
# names are machine-agnostic — each target publishes to its own repo stream,
# so contents differ per feed while names stay uniform across machines.
#
# RRECOMMENDS on the OOT supplementary packagegroup so OOT-provided modules
# (emitted from nvidia-kernel-oot_%.bbappend) install alongside without
# forcing a hard dep when building without OOT.
PACKAGES:append = " packagegroup-avocado-rootfs-modules packagegroup-avocado-initramfs-modules"
PKG:packagegroup-avocado-rootfs-modules = "packagegroup-avocado-rootfs-modules-${KERNEL_VERSION}"
PKG:packagegroup-avocado-initramfs-modules = "packagegroup-avocado-initramfs-modules-${KERNEL_VERSION}"
ALLOW_EMPTY:packagegroup-avocado-rootfs-modules = "1"
ALLOW_EMPTY:packagegroup-avocado-initramfs-modules = "1"
FILES:packagegroup-avocado-rootfs-modules = ""
FILES:packagegroup-avocado-initramfs-modules = ""
SUMMARY:packagegroup-avocado-rootfs-modules = "Kernel modules pulled into the Avocado rootfs for kernel ${KERNEL_VERSION}"
SUMMARY:packagegroup-avocado-initramfs-modules = "Kernel modules pulled into the Avocado initramfs for kernel ${KERNEL_VERSION}"

# See avocado-kernel-modules-packagegroup.inc for why the unqualified Provide
# is published alongside the versioned PKG NAME.
RPROVIDES:packagegroup-avocado-rootfs-modules = "packagegroup-avocado-rootfs-modules"
RPROVIDES:packagegroup-avocado-initramfs-modules = "packagegroup-avocado-initramfs-modules"

RDEPENDS:packagegroup-avocado-rootfs-modules = " \
    ${@bb.utils.contains('DISTRO_FEATURES','zram','kernel-module-zram-${KERNEL_VERSION}','',d)} \
"
RDEPENDS:packagegroup-avocado-initramfs-modules = " \
    kernel-module-nvme-${KERNEL_VERSION} \
    kernel-module-pcie-tegra194-${KERNEL_VERSION} \
    kernel-module-phy-tegra194-p2u-${KERNEL_VERSION} \
    kernel-module-tegra-xudc-${KERNEL_VERSION} \
    ${@bb.utils.contains('DISTRO_FEATURES','zram','kernel-module-zram-${KERNEL_VERSION}','',d)} \
"
