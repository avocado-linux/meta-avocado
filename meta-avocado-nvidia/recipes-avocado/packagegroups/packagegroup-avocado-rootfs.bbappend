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

# systemd-jetson-masks (disable the bare `getty@.service` preset that leaves
# every Jetson `degraded` with getty@getty.service) is wired into
# MACHINE_ESSENTIAL_EXTRA_RDEPENDS by avocado-jetson.inc, but
# packagegroup-avocado-rootfs.bb deliberately does not expand that variable
# (see above), so it never reached an avocado-built rootfs. Pull it in here.
RDEPENDS:${PN}:append:tegra = " systemd-jetson-masks"

# nvbootctrl is the slot tool for every Jetson OS update: the stone manifest's
# slot_detection, activate and rollback actions all call it. Until now it came
# only from the board's BSP extension (tegra-redundant-boot-base), but rollback
# runs at boot before extensions merge, so it failed with "Failed to run slot
# action command: No such file or directory" and left the board on the failed
# slot. It belongs in the base rootfs, like libubootenv-bin for U-Boot-env
# boards (packagegroup-avocado-rootfs.bb).
RDEPENDS:${PN}:append:tegra = " tegra-redundant-boot-base"
