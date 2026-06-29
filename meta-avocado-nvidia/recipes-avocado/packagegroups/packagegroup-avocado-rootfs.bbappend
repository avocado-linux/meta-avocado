# meta-tegra's tegra-common.inc adds `nvidia-kernel-oot-base` to
# MACHINE_ESSENTIAL_EXTRA_RDEPENDS, which packagegroup-avocado-rootfs.bb
# expands into its RDEPENDS. nvidia-kernel-oot-base is built only by the
# alt mc (jetson-l4t, linux-noble-nvidia-tegra 6.8) and has unversioned
# RDEPENDS on `nv-kernel-module-*` — packages that exist only at the alt
# mc's KERNEL_VERSION. Pulling nvidia-kernel-oot-base into the rootfs
# packagegroup therefore drags the entire L4T kernel chain into the
# resolution regardless of which kernel the rootfs is targeting, even
# when the lockfile pins linux-yocto 6.18.
#
# Strip it here. OOT modules are routed through the kernel-version-
# qualified packagegroup-avocado-rootfs-modules-oot-${KERNEL_VERSION}
# (emitted by nvidia-kernel-oot_%.bbappend); avocado-cli auto-appends
# that packagegroup from the lockfile pin when an OOT-using kernel is
# selected. Pinning a kernel without OOT (linux-yocto 6.18) skips the
# OOT packagegroup entirely — no leakage.
RDEPENDS:${PN}:remove = "nvidia-kernel-oot-base"
