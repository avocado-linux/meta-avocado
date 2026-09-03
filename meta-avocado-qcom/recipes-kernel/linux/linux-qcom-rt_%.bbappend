# PREEMPT_RT sibling of linux-qcom. meta-qcom's linux-qcom-rt_6.18.bb is just
# `require linux-qcom_6.18.bb` plus arch/arm64/configs/rt.config (which is only
# CONFIG_EXPERT=y + CONFIG_PREEMPT_RT=y); the board dts, the avocado cfg
# fragments and the feed classes all come from the shared .inc.
#
# Built in its own multiconfig (conf/multiconfig/qcom-rt.conf, activated by
# kas/feature/multi-kernel-qcom.yml) so the feed carries both kernels and
# avocado-cli's resolver can pick between them.
require recipes-kernel/linux/avocado-linux-qcom.inc

# The two kernels have to be told apart twice, because the feed keys on two
# different strings and this pair -- unlike Jetson's and Raspberry Pi's --
# is the same upstream version built twice.
#
#  1. ${KERNEL_VERSION} (kernel.release) names every per-kernel package:
#     kernel-${kver}, kernel-modules-${kver}, kernel-module-*-${kver},
#     kernel-devicetree-${kver}, packagegroup-avocado-{rootfs,initramfs}-
#     modules-${kver}, and the avocado-kernel-${kver} Provides on kernel-base
#     that avocado-cli enumerates to list the feed's kernels. rt.config leaves
#     CONFIG_LOCALVERSION empty and both recipes build the same SRCREV, so
#     without avocado-rt.cfg below both kernels come out as the identical
#     6.18.37-<scmversion> and every one of those names collides.
#
#  2. ${PV} names the four subpackages kernel.bbclass never version-qualifies:
#     kernel, kernel-dbg, kernel-dev, kernel-vmlinux. Jetson (6.18 vs 6.8) and
#     Raspberry Pi (6.12 vs 6.6) only avoid this because their two kernels
#     differ in PV. Here both are 6.18.37, so the RT build needs its own PV or
#     it ships a different payload under an identical NEVRA -- which trips
#     bitbake's shared-area guard in a local feed and, worse, puts two distinct
#     artifacts under one NEVRA in the Pulp repo, where nothing filters them.
#
# The suffix is ".rt", not the more obvious "+rt": a '+' in PV is OE's marker
# for the git-srcrev idiom (PV = "1.0+git" -> PKGV "1.0+git0+<srcrev>"), so
# "+rt" came out as 6.18.37+rt0+bfeb0e5567. That is still distinct, but it
# embeds the SRCREV in PV for the RT kernel only -- the stock kernel stays a
# plain 6.18.37 -- so the two disagree about what a version means and the RT
# one moves in an arbitrary direction on every kernel repin, since the trailing
# hex does not sort. "6.18.37.rt" just appends a segment: still above plain
# 6.18.37 under rpmvercmp, and still monotonic across a repin to 6.18.38.rt.
PV = "${LINUX_VERSION}.rt"

# Appended last so it wins the merge_config.sh -m pass: find_cfgs() feeds
# fragments in SRC_URI order and rt.config is merged before them.
SRC_URI += "file://avocado-rt.cfg"
