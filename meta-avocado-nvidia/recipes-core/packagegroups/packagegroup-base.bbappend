# meta-tegra's tegra-common.inc adds nvidia-kernel-oot-display to
# MACHINE_EXTRA_RDEPENDS and nvidia-kernel-oot-cameras / nvidia-kernel-oot-canbus
# to MACHINE_EXTRA_RRECOMMENDS. packagegroup-base.bb expands both into
# packagegroup-machine-base. After do_multikernel_merge puts the 5.15 OOT RPMs
# into the unified deploy tree, DNF can see these aggregate packages and installs
# them into the rootfs, dragging in nv-kernel-module-*-5.15 → kernel-5.15.* →
# 24 in-tree kernel-module-*-5.15 splits.
#
# Strip all three here. OOT display/camera/canbus modules are routed through the
# kernel-version-qualified packagegroup-avocado-rootfs-modules-oot-${KERNEL_VERSION}
# or listed explicitly in avocado.yaml; avocado-cli handles installation at
# provisioning time based on the pinned kernel.
RDEPENDS:packagegroup-machine-base:remove = "nvidia-kernel-oot-display"
RRECOMMENDS:packagegroup-machine-base:remove = "nvidia-kernel-oot-cameras nvidia-kernel-oot-canbus"
