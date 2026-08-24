# meta-tegra's tegra-common.inc adds nvidia-kernel-oot-display to
# MACHINE_EXTRA_RDEPENDS and nvidia-kernel-oot-cameras / nvidia-kernel-oot-canbus
# to MACHINE_EXTRA_RRECOMMENDS. packagegroup-base.bb expands both into
# packagegroup-machine-base. After do_multikernel_merge puts the 5.15 OOT RPMs
# into the unified deploy tree, DNF can see these aggregate packages and installs
# them into the rootfs, dragging in nv-kernel-module-*-5.15 → kernel-5.15.* →
# 24 in-tree kernel-module-*-5.15 splits.
#
# Strip them all here. OOT display/camera/canbus/alsa/bt modules are routed through
# the kernel-version-qualified packagegroup-avocado-rootfs-modules-oot-${KERNEL_VERSION}
# or listed explicitly in avocado.yaml; avocado-cli handles installation at
# provisioning time based on the pinned kernel.
#
# Two more arrived with the meta-tegra 727633de update, both by the same route:
#
#   nvidia-kernel-oot-alsa       tegra-common.inc absorbed the APE audio module
#                                list from the deleted devkit-audio.inc and added
#                                this alongside it, so it now reaches every Jetson
#                                directly. alsa-state.bbappend already strips it
#                                from that recipe's RDEPENDS, but this is a second,
#                                independent path to the rootfs.
#   nv-kernel-module-rtk-btusb   p3768.inc (Orin Nano/NX carrier) lists the OOT
#                                Realtek btusb module unconditionally -- unlike the
#                                wifi and ethernet entries beside it, it is NOT
#                                gated on PREFERRED_PROVIDER_virtual/kernel, so it
#                                lands even though we build linux-yocto. The
#                                nv- prefix is KERNEL_MODULE_PACKAGE_PREFIX from
#                                nvidia-kernel-oot.inc, i.e. the same OOT chain.
#                                p3737/p4071 use the unprefixed package instead.
#
# These replace the old tegra-wifi/tegra-bluetooth bbappends, which upstream
# obsoleted by deleting both recipes outright ("meta: drop obsolete tegra-wifi
# and tegra-bluetooth recipes").
RDEPENDS:packagegroup-machine-base:remove = "nvidia-kernel-oot-display"
RRECOMMENDS:packagegroup-machine-base:remove = "nvidia-kernel-oot-cameras nvidia-kernel-oot-canbus nvidia-kernel-oot-alsa nv-kernel-module-rtk-btusb"
