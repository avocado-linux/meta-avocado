FILESEXTRAPATHS:prepend := "${THISDIR}/linux-noble-nvidia-tegra:${THISDIR}/files:"

SRC_URI:append = " \
  file://avocado-core.cfg \
  file://avocado-extra.cfg \
"

# dm-crypt/dm-verity capability (shared fragments) + the OP-TEE fTPM driver.
# Unconditional: see avocado-security-kernel.inc for why capability is not
# gated on a DISTRO_FEATURE. files/ftpm.cfg is shared by both Jetson kernels.
require recipes-kernel/linux/avocado-security-kernel.inc
SRC_URI += " file://ftpm.cfg"

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

inherit avocado-kernel-feed
inherit avocado-kernel-builtin-provides

require recipes-kernel/linux/avocado-kernel-modules-packagegroup.inc

# See avocado-kernel-modules-packagegroup.inc for why the unqualified Provide
# is published alongside the versioned PKG NAME.
RPROVIDES:packagegroup-avocado-rootfs-modules = "packagegroup-avocado-rootfs-modules"
RPROVIDES:packagegroup-avocado-initramfs-modules = "packagegroup-avocado-initramfs-modules"

# Tegra hardware modules previously contributed via meta-tegra's unversioned
# MACHINE_ESSENTIAL_EXTRA_RRECOMMENDS in tegra-common.inc. Routed here as
# fully-qualified ${KERNEL_VERSION}-suffixed RDEPENDS so dnf installs this
# kernel's modules instead of NVR-tiebreaking against another kernel in the
# rolling feed. avocado-cli auto-appends this packagegroup whenever the
# rootfs is being installed and this kernel is the lockfile-pinned one.
RDEPENDS:packagegroup-avocado-rootfs-modules = " \
    kernel-module-ina3221-${KERNEL_VERSION} \
    kernel-module-lm90-${KERNEL_VERSION} \
    kernel-module-tegra-bpmp-thermal-${KERNEL_VERSION} \
    kernel-module-spi-tegra114-${KERNEL_VERSION} \
    kernel-module-pwm-fan-${KERNEL_VERSION} \
    kernel-module-governor-userspace-${KERNEL_VERSION} \
    kernel-module-ucsi-ccg-${KERNEL_VERSION} \
    kernel-module-pcie-tegra194-${KERNEL_VERSION} \
    kernel-module-phy-tegra194-p2u-${KERNEL_VERSION} \
    kernel-module-nvme-${KERNEL_VERSION} \
    kernel-module-pwm-tegra-${KERNEL_VERSION} \
    kernel-module-tegra-xudc-${KERNEL_VERSION} \
    kernel-module-lz4-${KERNEL_VERSION} \
    kernel-module-lz4-compress-${KERNEL_VERSION} \
    kernel-module-sch-fq-codel-${KERNEL_VERSION} \
    ${@bb.utils.contains('DISTRO_FEATURES','zram','kernel-module-zram-${KERNEL_VERSION}','',d)} \
"
RDEPENDS:packagegroup-avocado-initramfs-modules = " \
    kernel-module-nvme-${KERNEL_VERSION} \
    kernel-module-pcie-tegra194-${KERNEL_VERSION} \
    kernel-module-phy-tegra194-p2u-${KERNEL_VERSION} \
    kernel-module-tegra-xudc-${KERNEL_VERSION} \
    kernel-module-tpm-ftpm-tee-${KERNEL_VERSION} \
    kernel-module-dm-mod-${KERNEL_VERSION} \
    kernel-module-dm-crypt-${KERNEL_VERSION} \
"

# Pull the OOT initramfs/rootfs packagegroups in alongside the kernel-owned
# ones. avocado-cli auto-appends packagegroup-avocado-{rootfs,initramfs}-
# modules-${KV} but has no native awareness of the OOT siblings emitted
# from nvidia-kernel-oot_%.bbappend, so without this hard dep the OOT
# modules (tegra-bpmp, mc-utils, nvmap, host1x, pcie-tegra264 — anything
# pcie-tegra264 transitively needs to probe) are never installed and the
# NVMe never enumerates on Thor.
#
# Use the unqualified name (not ...-${KERNEL_VERSION}): KERNEL_VERSION is
# computed from the kernel build dir at do_compile time, so referencing it
# inside an RDEPENDS string gets the literal "None" at parse-time RDEPENDS
# resolution (KERNEL_MODULE_PACKAGE_SUFFIX is the late-bound form, but
# kernel-module-split.bbclass only handles that for kernel-module-* names
# via do_split_packages — packagegroups have no equivalent magic). The
# unqualified RPROVIDES on the OOT packagegroup makes this resolve cleanly.
#
# Kept in the kernel bbappends rather than the shared
# avocado-kernel-modules-packagegroup.inc so each kernel opts in explicitly.
# This was originally noble-only because linux-yocto 6.18 had no
# nvidia-kernel-oot build and therefore no OOT sibling to depend on; that is no
# longer true, and linux-yocto_6.18.bbappend now carries the same two lines.
# Boot on tegra264 depends on it -- see the note there.
RDEPENDS:packagegroup-avocado-initramfs-modules:append = " packagegroup-avocado-initramfs-modules-oot"
RDEPENDS:packagegroup-avocado-rootfs-modules:append = " packagegroup-avocado-rootfs-modules-oot"
