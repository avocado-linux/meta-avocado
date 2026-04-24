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

# Rename kernel-devsrc to include KERNEL_VERSION so multiple kernel versions
# can coexist in a rolling feed. Under Path B's discipline (no unqualified
# kernel-family virtuals), only the versioned name is published. Callers
# select kernel-devsrc via `{{ avocado.kernel.version }}` templating in their
# avocado.yaml.
PKG:${KERNEL_PACKAGE_NAME}-devsrc = "${KERNEL_PACKAGE_NAME}-devsrc-${KERNEL_VERSION}"

# Publish a well-known virtual that avocado-cli's kernel resolver queries
# with `dnf repoquery --whatprovides 'avocado-kernel-*' --provides`. Encodes
# KERNEL_VERSION in the Provide name so the resolver can enumerate every
# kernel available in the feed without fishing through package NAMEs or
# relying on kernel.bbclass's (nonexistent) unqualified `kernel` Provide.
RPROVIDES:${KERNEL_PACKAGE_NAME}-base += "avocado-kernel-${KERNEL_VERSION}"
