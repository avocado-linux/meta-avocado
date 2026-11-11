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

# Debug-info kernel. The kernel CVE filter (do_kernel_cve_improve in
# meta-avocado-sbom) needs the kernel's DWARF to know which sources this
# configuration compiles, and a scan run on top of a feed build has to see the
# kernel the feed published. kas/feature/sbom.yml and kas/feature/cve-check.yml
# set this. The DWARF is split into ${KERNEL_PACKAGE_NAME}-dbg, so the packages
# a device installs stay stripped. The compiled-file list the filter reads comes
# from the recipe's SPDX document.
#
# KERNEL_EXTRA_FEATURES reaches the linux-yocto recipes only. A kernel that does
# not read it (linux-raspberrypi) keys a config fragment off the same switch in
# its own bbappend.
AVOCADO_KERNEL_DEBUGINFO ??= "0"
KERNEL_EXTRA_FEATURES:append = "${@' features/debug/debug-kernel.scc' if d.getVar('AVOCADO_KERNEL_DEBUGINFO') == '1' else ''}"

# DEBUG_KERNEL also un-gates runtime debug options (kgdb/kdb, SCHED_DEBUG,
# CGROUP_DEBUG, RCU_TRACE, ...) that kernel-cache fragments in the BSP already
# request. Where DEBUG_KERNEL is already on without the switch (intel-x86-64
# from x86_64_defconfig, genericarm64 through EXPERT, the arm64 defconfig for
# linux-yocto-dev), those options ship today and the switch adds debug info
# only. A layer whose machine has DEBUG_KERNEL off sets
# AVOCADO_KERNEL_DEBUGINFO_RUNTIME_OFF = "1" for it, and
# avocado/debug-kernel-runtime-off.scc turns them back off.
#
# It must come after every fragment that requests them: do_kernel_metadata
# hands scc the BSP definition, then the SRC_URI fragments, then
# KERNEL_FEATURES in order, and merge_config.sh lets a later fragment win.
# Appending from anonymous python puts it after every KERNEL_FEATURES append in
# conf, recipe and bbappends, since those are all parsed by the time it runs.
# The kmeta directory puts the feature on scc's search path; as a plain SRC_URI
# fragment it would sit before KERNEL_FEATURES.
AVOCADO_KERNEL_DEBUGINFO_RUNTIME_OFF ??= "0"
python __anonymous() {
    if d.getVar('AVOCADO_KERNEL_DEBUGINFO') == '1' and \
            d.getVar('AVOCADO_KERNEL_DEBUGINFO_RUNTIME_OFF') == '1' and \
            d.getVar('PN').startswith('linux-yocto'):
        d.prependVar('FILESEXTRAPATHS', d.getVar('AVOCADO_LAYER_DIR') + '/files:')
        d.appendVar('SRC_URI', ' file://avocado-kmeta;type=kmeta;destsuffix=avocado-kmeta')
        d.appendVar('KERNEL_FEATURES', ' avocado/debug-kernel-runtime-off.scc')
}
