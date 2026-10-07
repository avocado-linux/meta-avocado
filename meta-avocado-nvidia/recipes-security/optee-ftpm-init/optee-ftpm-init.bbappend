# avocado-tegra-init masks optee-ftpm-setup.service and runs the script itself
# once it knows the boot disk. The systemd class postinst runs the real
# `systemctl enable`, which refuses a masked unit, so do not enable it here
# (same as cryptsetup-var on Jetson). The mask wins over the static
# initrd-root-fs.target.wants link too.
SYSTEMD_AUTO_ENABLE:${PN}:tegra = "disable"
