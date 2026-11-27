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

# Debug-info kernel, for the kernel CVE filter: sbom-cve-check drops a CVE whose
# affected files this configuration does not compile, and reads that list from
# the kernel's SPDX document (SPDX_INCLUDE_COMPILED_SOURCES), which OE-core
# fills from the kernel's debug sources. kas/feature/sbom.yml sets the switch so
# a scan sees the kernel the feed published. The DWARF lands in
# ${KERNEL_PACKAGE_NAME}-dbg; what a device installs stays stripped.
#
# linux-yocto and linux-yocto-dev only. linux-yocto-rt also reads
# KERNEL_EXTRA_FEATURES and inherits this class, so the PN test is what keeps
# it, and every vendor kernel, unchanged. linux-raspberrypi and the L4T kernels
# key a config fragment off the same switch in their own bbappends.
#
# Not with module-signing: OE-core neither splits nor strips a signed module,
# so its DWARF would ship and its sources would be missing from the list, and a
# CVE in it would read as not compiled. Such a build keeps the kernel as it is
# and turns its SPDX source lists off. spdx-common has already set
# SPDX_INCLUDE_SOURCES from the kas line by the time this runs, hence both
# overrides.
#
# Where DEBUG_KERNEL is off without the switch, turning it on also un-gates
# runtime debug options the BSP's kernel-cache fragments request. A layer with
# such a machine sets AVOCADO_KERNEL_DEBUGINFO_RUNTIME_OFF = "1" for it, and
# avocado/debug-kernel-runtime-off.scc turns them back off. It has to follow
# every fragment that requests them (merge_config.sh lets a later fragment
# win), and anonymous python runs after every KERNEL_FEATURES append has been
# parsed. The kmeta directory puts the feature on scc's search path; as a plain
# SRC_URI fragment it would sit before KERNEL_FEATURES.
AVOCADO_KERNEL_DEBUGINFO ??= "0"
AVOCADO_KERNEL_DEBUGINFO_RUNTIME_OFF ??= "0"
python __anonymous() {
    pn = d.getVar('PN')
    if d.getVar('AVOCADO_KERNEL_DEBUGINFO') != '1' or \
            pn not in ('linux-yocto', 'linux-yocto-dev'):
        return
    if bb.utils.contains('DISTRO_FEATURES', 'module-signing', True, False, d):
        d.setVar('SPDX_INCLUDE_COMPILED_SOURCES:pn-' + pn, '0')
        d.setVar('SPDX_INCLUDE_SOURCES:pn-' + pn, '0')
        return
    d.appendVar('KERNEL_FEATURES', ' features/debug/debug-kernel.scc')
    if d.getVar('AVOCADO_KERNEL_DEBUGINFO_RUNTIME_OFF') == '1':
        d.prependVar('FILESEXTRAPATHS', d.getVar('AVOCADO_LAYER_DIR') + '/files:')
        d.appendVar('SRC_URI', ' file://avocado-kmeta;type=kmeta;destsuffix=avocado-kmeta')
        d.appendVar('KERNEL_FEATURES', ' avocado/debug-kernel-runtime-off.scc')
}
