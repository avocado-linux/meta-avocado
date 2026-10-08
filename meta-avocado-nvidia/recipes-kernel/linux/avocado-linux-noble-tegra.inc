# Shared by the L4T family on Jetson: linux-noble-nvidia-tegra (jetson-l4t mc)
# and linux-noble-nvidia-tegra-rt (jetson-l4t-rt mc). meta-tegra's RT recipe is
# `require linux-noble-nvidia-tegra.inc` plus TEGRA_LINUX_VERSION_EXTENSION and
# enable-preempt-rt.cfg, so the two share a source tree and a files directory.

require recipes-kernel/linux/avocado-linux-tegra.inc

FILESEXTRAPATHS:prepend := "${THISDIR}/linux-noble-nvidia-tegra:${THISDIR}/files:"

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
#
# This is also what keeps the two L4T kernels' KERNEL_VERSIONs stable enough to
# tell apart: with the SHA suppressed they differ only by the "-rt" that
# TEGRA_LINUX_VERSION_EXTENSION puts on LINUX_VERSION_EXTENSION.
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
