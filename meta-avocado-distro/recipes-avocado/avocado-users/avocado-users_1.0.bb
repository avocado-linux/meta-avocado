DESCRIPTION = "Avocado Linux users"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

inherit allarch

# Configuration variable to allow root login with empty password
# Set AVOCADO_DEV_ROOT_LOGIN = "1" in local.conf to enable
AVOCADO_DEV_ROOT_LOGIN ??= "0"

SRC_URI = " \
  file://passwd \
  file://shadow \
  file://group \
  file://gshadow \
  file://var-resize.service \
  file://var-roothome-init.service \
"

inherit systemd
SYSTEMD_SERVICE:${PN} = "var-resize.service var-roothome-init.service"

do_install() {
    install -d ${D}${sysconfdir}
    install -m 0644 ${WORKDIR}/passwd ${D}${sysconfdir}/passwd
    install -m 0644 ${WORKDIR}/group ${D}${sysconfdir}/group
    install -m 0644 ${WORKDIR}/gshadow ${D}${sysconfdir}/gshadow

    # Handle shadow file with optional root login configuration
    if [ "${AVOCADO_DEV_ROOT_LOGIN}" = "1" ]; then
        # Enable root login with empty password by setting empty password field
        sed 's/^root:\*:/root::/' ${WORKDIR}/shadow > ${D}${sysconfdir}/shadow
        bbwarn "Root login with empty password is enabled. This is insecure and should only be used for development!"
    else
        # Use default shadow file (root login disabled)
        install -m 0644 ${WORKDIR}/shadow ${D}${sysconfdir}/shadow
    fi

    # sshd privilege separation directory
    install -d -m 0755 ${D}/var/empty/sshd

    # Root home on writable /var partition (read-only rootfs)
    install -d -m 0700 ${D}/var/roothome

    # /var/log for lastlog and journal
    install -d -m 0755 ${D}/var/log

    # Systemd services for first-boot setup
    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${WORKDIR}/var-resize.service ${D}${systemd_system_unitdir}/
    install -m 0644 ${WORKDIR}/var-roothome-init.service ${D}${systemd_system_unitdir}/
}
do_install[vardeps] += "AVOCADO_DEV_ROOT_LOGIN"
