# Avocado's rootfs is read-only and ships an empty /home, so weston.service's
# WorkingDirectory=/home/weston fails at chdir (status=200/CHDIR) and the
# compositor never starts. A drop-in moves weston's home to a state
# directory on the writable /var; it also covers machines that replace
# weston.service.
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += "file://avocado-weston-home.conf"

FILES:${PN} += "${systemd_system_unitdir}/weston.service.d"

do_install:append() {
    install -Dm 0644 ${UNPACKDIR}/avocado-weston-home.conf \
        ${D}${systemd_system_unitdir}/weston.service.d/avocado-weston-home.conf
}
