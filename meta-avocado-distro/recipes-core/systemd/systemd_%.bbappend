FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
SRC_URI:append = " file://zram-generator.conf"
SRC_URI:append = " file://wait-online-any.conf"

do_install:append () {
    install -m 0644 ${UNPACKDIR}/zram-generator.conf ${D}${sysconfdir}/systemd/

    # Stop network-online.target waiting 120s for an unconnected port.
    #
    # The drop-in's ExecStart carries a placeholder rather than a literal
    # /usr/lib/systemd or /lib/systemd path: which one is correct depends on
    # whether usrmerge is in DISTRO_FEATURES, and hardcoding the usrmerge
    # answer here would point ExecStart at nothing and fail the unit silently
    # the day usrmerge is dropped. rootlibexecdir already carries that answer.
    install -d ${D}${sysconfdir}/systemd/system/systemd-networkd-wait-online.service.d
    install -m 0644 ${UNPACKDIR}/wait-online-any.conf \
        ${D}${sysconfdir}/systemd/system/systemd-networkd-wait-online.service.d/
    sed -i "s|@ROOTLIBEXECDIR@|${rootlibexecdir}|" \
        ${D}${sysconfdir}/systemd/system/systemd-networkd-wait-online.service.d/wait-online-any.conf

    # Mask upstream systemd-sysext/confext units.
    # Avocado replaces these with avocado-extension.service and
    # avocado-extension-initrd.service (via avocadoctl).
    # The sysext socket has a static symlink in
    # /lib/systemd/system/sockets.target.wants/ that bypasses presets,
    # so masking (-> /dev/null) is required.
    install -d ${D}${sysconfdir}/systemd/system
    ln -sf /dev/null ${D}${sysconfdir}/systemd/system/systemd-sysext.socket
    ln -sf /dev/null ${D}${sysconfdir}/systemd/system/systemd-sysext.service
    ln -sf /dev/null ${D}${sysconfdir}/systemd/system/systemd-sysext-initrd.service
    ln -sf /dev/null ${D}${sysconfdir}/systemd/system/systemd-confext.socket
    ln -sf /dev/null ${D}${sysconfdir}/systemd/system/systemd-confext.service
}
