# meta-tegra's alsa-state.bbappend appends nvidia-kernel-oot-alsa to
# RDEPENDS:${PN}:tegra. In the multi-kernel feed the OOT 5.15 package is
# present, so DNF installs it into the rootfs, dragging in the full L4T 5.15
# kernel chain. OOT ALSA modules are installed by avocado-cli at provisioning
# time based on the pinned kernel version.
RDEPENDS:${PN}:remove = "nvidia-kernel-oot-alsa"
