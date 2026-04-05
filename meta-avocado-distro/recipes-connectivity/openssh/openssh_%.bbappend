FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += " \
    file://sshd_config_avocado \
    file://sshd_check_keys_avocado \
    file://sshdgenkeys-avocado.conf \
    file://sshd-daemon.service \
"

do_install:append() {
    # Use Avocado sshd_config — host keys on writable /var, not read-only /etc
    install -m 0644 ${WORKDIR}/sshd_config_avocado ${D}${sysconfdir}/ssh/sshd_config

    # Install key generation script that writes to /var/lib/ssh
    install -m 0755 ${WORKDIR}/sshd_check_keys_avocado ${D}${libexecdir}/openssh/sshd_check_keys_avocado

    # Override sshdgenkeys.service to use our key generation script
    install -d ${D}${systemd_system_unitdir}/sshdgenkeys.service.d
    install -m 0644 ${WORKDIR}/sshdgenkeys-avocado.conf \
        ${D}${systemd_system_unitdir}/sshdgenkeys.service.d/avocado-keylocation.conf

    # Use standalone sshd daemon instead of socket activation.
    # Socket-activated sshd (sshd -i mode) silently fails on read-only rootfs
    # because the per-connection sshd@ service cannot write state files.
    install -m 0644 ${WORKDIR}/sshd-daemon.service ${D}${systemd_system_unitdir}/sshd.service
    rm -f ${D}${systemd_system_unitdir}/sshd.socket
    rm -f ${D}${systemd_system_unitdir}/sshd@.service

    # Create /var/lib/ssh directory in image
    install -d ${D}/var/lib/ssh
}

SYSTEMD_SERVICE:${PN}-sshd = "sshd.service"
