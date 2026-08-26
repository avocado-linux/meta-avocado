SUMMARY = "Disable the virtual-console getty preset on serial-console-only boards"
DESCRIPTION = "OE-core's 90-systemd.preset enables the getty@.service template \
without an instance. The offline enabler turns that into a bare getty@.service \
symlink in getty.target.wants, systemd instantiates it as getty@getty.service, \
agetty fails to open /dev/getty (208/STDIN), hits the restart limit and leaves \
the system 'degraded' on every boot. On a board with no virtual console the \
login prompt comes from serial-getty@<console>.service via \
systemd-getty-generator, which does not depend on this preset, so disabling \
it costs nothing. Presets are first-match-wins in lexicographic order; 89- \
beats 90-. Pull this package into the rootfs of any machine without a VT."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

inherit allarch features_check
REQUIRED_DISTRO_FEATURES = "systemd"

do_install() {
    install -d ${D}${nonarch_libdir}/systemd/system-preset
    cat > ${D}${nonarch_libdir}/systemd/system-preset/89-avocado-serial-console.preset <<PRESET
disable getty@.service
PRESET
}

FILES:${PN} = "${nonarch_libdir}/systemd/system-preset/89-avocado-serial-console.preset"
