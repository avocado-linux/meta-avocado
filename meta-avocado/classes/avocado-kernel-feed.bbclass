# Boilerplate every Avocado kernel bbappend needs to participate in a
# multi-kernel rolling feed. Inherit from each kernel bbappend in
# meta-avocado-{family}/recipes-kernel/linux/.
#
# Two packages emitted by upstream classes ship under unqualified NAMEs and
# would NVR-tiebreak in a feed that carries more than one kernel:
#   * kernel-devicetree   (kernel-devicetree.bbclass)
#   * kernel-modules      (kernel-module-split.bbclass with KERNEL_SPLIT_MODULES=1,
#                          which is OE's default and ours)
# Rename them to kernel-${PACKAGE}-${KERNEL_VERSION} and republish the
# unqualified Provide so:
#   - existing callers listing the bare NAME (e.g. `kernel-modules` in
#     packagegroups) still resolve at install time, and
#   - explicit pinners and avocado-cli's `-${KERNEL_VERSION}` auto-suffix
#     resolve to the resolver-pinned kernel.
#
# Also publishes the avocado-cli kernel-resolver virtual on the -base package
# so `dnf repoquery --whatprovides 'avocado-kernel-*' --provides` enumerates
# every kernel in the feed.
#
# Per-family bits (SRC_URI fragments, COMPATIBLE_MACHINE, patches,
# packagegroup setup with family-specific module RDEPENDS, SCMVERSION
# tweaks, ...) stay in the bbappend.
#
# kernel-devsrc is a recipe of its own, not a package of the kernel recipe, so
# its per-kernel rename lives in
# meta-avocado-distro/recipes-kernel/linux/kernel-devsrc.bbappend.

PKG:${KERNEL_PACKAGE_NAME}-devicetree  = "${KERNEL_PACKAGE_NAME}-devicetree-${KERNEL_VERSION}"
PKG:${KERNEL_PACKAGE_NAME}-modules     = "${KERNEL_PACKAGE_NAME}-modules-${KERNEL_VERSION}"

RPROVIDES:${KERNEL_PACKAGE_NAME}-devicetree  += "kernel-devicetree kernel-devicetree-${KERNEL_VERSION}"
RPROVIDES:${KERNEL_PACKAGE_NAME}-modules     += "kernel-modules kernel-modules-${KERNEL_VERSION}"

RPROVIDES:${KERNEL_PACKAGE_NAME}-base += "avocado-kernel-${KERNEL_VERSION}"
