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
set_scmversion() {
    # Empty .scmversion preempts Kbuild's scripts/setlocalversion git lookup
    # (it cat's and returns immediately when the file exists).
    : > ${S}/.scmversion
}

# Rename kernel-devsrc to include KERNEL_VERSION so multiple kernel versions can
# coexist in a rolling feed without colliding on the unversioned package name.
# Mirrors the kernel-module-split convention (PKG = base-<KERNEL_VERSION>, plus
# both unqualified and versioned RPROVIDES). The avocado-cli resolver targets
# the versioned name; the unqualified Provides keeps `dnf install kernel-devsrc`
# working for manual flows.
PKG:${KERNEL_PACKAGE_NAME}-devsrc = "${KERNEL_PACKAGE_NAME}-devsrc-${KERNEL_VERSION}"
RPROVIDES:${KERNEL_PACKAGE_NAME}-devsrc += "kernel-devsrc kernel-devsrc-${KERNEL_VERSION}"
