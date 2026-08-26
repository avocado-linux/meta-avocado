# meta-tegra's recipe runs `sed '/create reboot/,/overlayfs_check/d'` on NVIDIA's
# flashing-initramfs /init, which drops the mount block it means to replace but
# also NVIDIA's /sbin/reboot wrapper ("busybox reboot -f"). PID 1 in that
# initramfs is /bin/bash, so bare busybox `reboot` -- which only signals init --
# is a silent no-op from init's own error/timeout paths, from the debug bash
# prompt and from `adb shell reboot`. Restore the wrapper as an
# update-alternative for reboot, above busybox's priority (50).
#
# Kept here rather than in the vendor layer: we do not carry meta-tegra patches.

do_compile:append() {
    cat >"${B}/reboot" <<'EOS'
#!/bin/sh
exec busybox reboot -f "$@"
EOS
}

do_install:append() {
    install -m 0755 -D ${B}/reboot ${D}${base_sbindir}/reboot.${BPN}
}

inherit update-alternatives
ALTERNATIVE:${PN} = "reboot"
ALTERNATIVE_LINK_NAME[reboot] = "${base_sbindir}/reboot"
ALTERNATIVE_TARGET[reboot] = "${base_sbindir}/reboot.${BPN}"
ALTERNATIVE_PRIORITY = "100"
