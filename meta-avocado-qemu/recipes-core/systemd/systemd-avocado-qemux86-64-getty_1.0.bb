SUMMARY = "Avocado-qemux86-64 getty fix: kill getty@getty loop, run getty@tty1"
DESCRIPTION = "OE-core's /lib/systemd/system-preset/90-systemd.preset ships \
`enable getty@.service` — the bare template with no instance — which lands in \
getty.target.wants and instantiates as `getty@getty.service`; agetty then fails \
to open /dev/getty (208/STDIN) and restart-loops forever, spamming the journal. \
An 89- preset (first-match-wins over 90-) disables the bare template, and we \
ship an explicit getty@tty1 wants symlink (preset-all cannot instantiate a \
template from an `enable getty@tty1.service` line, so the symlink is direct)."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

inherit features_check
REQUIRED_DISTRO_FEATURES = "systemd"

PACKAGE_ARCH = "${MACHINE_ARCH}"

do_install() {
    # 89- beats OE-core's 90-systemd.preset: stop the bare-template enable that
    # loops as getty@getty.
    install -d ${D}${nonarch_libdir}/systemd/system-preset
    echo "disable getty@.service" > ${D}${nonarch_libdir}/systemd/system-preset/89-avocado-qemux86-64-getty.preset

    # Enable getty on tty1 directly (preset-all won't instantiate a template).
    install -d ${D}${sysconfdir}/systemd/system/getty.target.wants
    ln -sf ${systemd_system_unitdir}/getty@.service \
        ${D}${sysconfdir}/systemd/system/getty.target.wants/getty@tty1.service
}

FILES:${PN} = " \
    ${nonarch_libdir}/systemd/system-preset/89-avocado-qemux86-64-getty.preset \
    ${sysconfdir}/systemd/system/getty.target.wants/getty@tty1.service \
"
