# meta-tegra's tegra-wifi_1.0.bb has RRECOMMENDS += "nvidia-kernel-oot-wifi".
# In the multi-kernel feed the OOT 5.15 package is present, so DNF installs
# it into the rootfs, dragging in the full L4T 5.15 kernel chain. OOT WiFi
# modules are installed by avocado-cli at provisioning time based on the
# pinned kernel version.
RRECOMMENDS:${PN}:remove = "nvidia-kernel-oot-wifi"
