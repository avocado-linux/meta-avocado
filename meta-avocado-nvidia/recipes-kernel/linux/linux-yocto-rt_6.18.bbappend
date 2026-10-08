# PREEMPT_RT sibling of linux-yocto, built in the jetson-rt multiconfig
# (meta-avocado-nvidia/conf/multiconfig/jetson-rt.conf, activated by
# kas/feature/multi-kernel-jetson.yml) so the feed carries it alongside the
# stock linux-yocto and avocado-cli's resolver can pick between them.
#
# oe-core's linux-yocto-rt_6.18.bb is the same 6.18 yocto-kernel tree on
# KBRANCH v6.18/standard/preempt-rt/base with LINUX_KERNEL_TYPE = "preempt-rt";
# meta-tegra's own linux-yocto-rt_6.18.bbappend supplies the tegra BSP
# (linux-yocto-tegra.inc, which also relaxes oe-core's qemu-only
# COMPATIBLE_MACHINE) plus features/tegra/rt-compat.scc. Everything Avocado
# adds comes from the shared .incs.
#
# No PV disambiguation is needed here, unlike the L4T pair and unlike qcom --
# but the reason is invisible to `bitbake -e`, so it is worth writing down.
#
# Both recipes sit at LINUX_VERSION 6.18.35 and both report
# PV = PKGV = "6.18.35+git" at parse time, which reads like exactly the same
# NEVRA collision the L4T pair has. It is not. A PKGV containing '+' is
# expanded at do_package, not at parse: package.bbclass's package_setup_pkgv
# PACKAGEFUNC appends bb.fetch.get_pkgv_string(d), the SRCREV-derived
# sortable_revision string assembled per SRCREV_FORMAT. meta-tegra's
# linux-yocto-tegra.inc sets SRCREV_FORMAT:tegra = "meta_machine_tegrameta",
# and the two recipes pin different SRCREV_machine (efc05d9af9... vs
# 35a623d1a7...), so the expanded PKGVs differ.
#
# That is what keeps the four subpackages kernel.bbclass never
# version-qualifies -- kernel, kernel-dbg, kernel-dev, kernel-vmlinux -- on
# distinct NEVRAs with no PV suffix here.
#
# The dependency is real: if the two recipes ever converge on one
# SRCREV_machine, or linux-yocto drops the '+git' idiom from PV, this pair
# starts colliding silently and needs the same PV = "${LINUX_VERSION}.rt"
# treatment the L4T sibling carries. Only a real build shows the expanded
# value -- compare the two kernels' RPM filenames under deploy/rpm.
#
# KERNEL_VERSION differs regardless: LINUX_VERSION_EXTENSION is
# "-yocto-${LINUX_KERNEL_TYPE}", so 6.18.35-yocto-standard vs
# 6.18.35-yocto-preempt-rt -- which is what keeps every kernel-module-* and
# per-kernel packagegroup name apart.
require recipes-kernel/linux/avocado-linux-yocto-tegra.inc
