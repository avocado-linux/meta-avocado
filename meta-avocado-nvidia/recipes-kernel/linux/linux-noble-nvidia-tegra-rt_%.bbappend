# PREEMPT_RT sibling of linux-noble-nvidia-tegra: NVIDIA's own RT kernel for
# Jetson, built in the jetson-l4t-rt multiconfig
# (meta-avocado-nvidia/conf/multiconfig/jetson-l4t-rt.conf, activated by
# kas/feature/multi-kernel-jetson.yml).
#
# meta-tegra's linux-noble-nvidia-tegra-rt_6.8.bb is `require
# linux-noble-nvidia-tegra.inc` with TEGRA_LINUX_VERSION_EXTENSION = "-rt" and
# enable-preempt-rt.cfg; the board config, the avocado cfg fragments and the
# feed classes all come from the shared .incs.
require recipes-kernel/linux/avocado-linux-noble-tegra.inc

# This pair, unlike the linux-yocto one, is the SAME upstream version built
# twice: linux-noble-nvidia-tegra.inc sets a plain PV = "${LINUX_VERSION}" (no
# '+git' srcrev expansion) and both recipes pin the same SRCREV, so both come
# out as 6.8.12.
#
# ${KERNEL_VERSION} is already distinct -- TEGRA_LINUX_VERSION_EXTENSION puts
# "-rt" on the end of LINUX_VERSION_EXTENSION -- so every name that carries it
# is safe: kernel-${kver}, kernel-module-*-${kver}, and the per-kernel
# packagegroup-avocado-{rootfs,initramfs}-modules-${kver}.
#
# ${PV} is not, and it names the four subpackages kernel.bbclass never
# version-qualifies: kernel, kernel-dbg, kernel-dev, kernel-vmlinux. Without
# this the RT build ships a different payload under an identical NEVRA -- which
# trips bitbake's shared-area guard in a local feed and, worse, puts two
# distinct artifacts under one NEVRA in the Pulp repo, where nothing filters
# them.
#
# The suffix is ".rt", not the more obvious "+rt", for the reason spelled out
# in meta-avocado-qcom/recipes-kernel/linux/linux-qcom-rt_%.bbappend: a '+' in
# PV is OE's marker for the git-srcrev idiom, so "+rt" would come out as
# 6.8.12+rt0+<srcrev> and embed the SRCREV in PV for the RT kernel only, moving
# in an arbitrary direction on every L4T repin. "6.8.12.rt" just appends a
# segment: still above plain 6.8.12 under rpmvercmp, and still monotonic across
# a repin to 6.8.13.rt.
PV = "${LINUX_VERSION}.rt"
