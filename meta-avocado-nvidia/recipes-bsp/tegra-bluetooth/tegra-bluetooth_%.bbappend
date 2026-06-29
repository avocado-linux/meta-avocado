# meta-tegra's tegra-bluetooth_1.0.bb has an unconditional
# RDEPENDS on nvidia-kernel-oot-bluetooth. In the multi-kernel feed the OOT
# package is present, so DNF installs it into the rootfs, dragging in
# the full L4T kernel chain. OOT bluetooth modules are installed by
# avocado-cli at provisioning time based on the pinned kernel version.
RDEPENDS:${PN}:remove = "nvidia-kernel-oot-bluetooth"
