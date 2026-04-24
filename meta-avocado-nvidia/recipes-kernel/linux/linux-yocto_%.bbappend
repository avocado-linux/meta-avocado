FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
  file://0001-mailbox-tegra-hsp-backport-L4T-shared-interrupt-mapping.patch \
  file://0002-mailbox-tegra-hsp-enable-per-mailbox-empty-interrupt.patch \
"

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
