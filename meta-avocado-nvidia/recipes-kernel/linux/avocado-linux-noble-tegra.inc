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

# KVM on Jetson AGX Orin: guests under the 6.8 kernel failed pointer
# authentication (6.8 loads a guest's PAuth keys lazily, on a trap). Upstream
# loads them eagerly since 6.10; backported. Both L4T kernels (stock and RT).
SRC_URI += " file://0001-KVM-arm64-Drop-trapping-of-PAuth-instructions-keys.patch"

# The Tegra I2C controllers. The L4T 6.8 kernel builds their drivers as modules
# (CONFIG_I2C=m, CONFIG_I2C_TEGRA=m, CONFIG_I2C_TEGRA_BPMP=m) and no module list
# carried them, so a 6.8 image had no I2C adapter at all: nothing on I2C bound,
# from the INA3221 and LM90 sensors in the shared Jetson list to every device on
# the camera buses. i2c-tegra autoloads from its device tree alias, so the
# package is all that is missing.
#
# Not in the shared Jetson list: linux-yocto 6.18 builds both drivers in
# (CONFIG_I2C_TEGRA=y), so no kernel-module-i2c-tegra package exists there and a
# dependency on it would not resolve.
RDEPENDS:packagegroup-avocado-rootfs-modules:append = " \
    kernel-module-i2c-tegra-${KERNEL_VERSION} \
    kernel-module-i2c-tegra-bpmp-${KERNEL_VERSION} \
"
