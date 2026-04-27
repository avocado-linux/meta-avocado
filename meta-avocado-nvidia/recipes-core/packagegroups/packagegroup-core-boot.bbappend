# Mirror of meta-avocado-nvidia/recipes-avocado/packagegroups/packagegroup-
# avocado-rootfs.bbappend. packagegroup-core-boot is the oe-core base boot
# packagegroup; it also expands ${MACHINE_ESSENTIAL_EXTRA_RDEPENDS} into its
# RDEPENDS, so meta-tegra's `nvidia-kernel-oot-base` flows in here too. Strip
# it via the same :remove so packagegroup-avocado-rootfs (which RDEPENDs on
# packagegroup-core-boot) doesn't pick the alt-mc OOT chain back up
# transitively.
#
# OOT modules are routed through the kernel-version-qualified
# packagegroup-avocado-rootfs-modules-oot-${KERNEL_VERSION} (emitted by
# nvidia-kernel-oot_%.bbappend) and auto-appended by avocado-cli from the
# lockfile pin.
RDEPENDS:${PN}:remove = "nvidia-kernel-oot-base"
