SUMMARY = "Enable the virtual-console getty on tty1 on boards with a display"
DESCRIPTION = "OE-core's 90-systemd.preset enables the getty@.service template \
without an instance, which the offline enabler turns into a bare getty@.service \
symlink; systemd then runs getty@getty.service, agetty cannot open /dev/getty, \
and a board with a monitor never shows a login prompt (seen on the DGX Spark). \
Name the instance instead. Presets are first-match-wins in lexicographic \
order; 89- beats 90-. The serial-console counterpart for boards without a VT \
is systemd-serial-console-preset. Pull this package into the rootfs of any \
machine with a virtual console."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

inherit allarch features_check
REQUIRED_DISTRO_FEATURES = "systemd"

do_install() {
    install -d ${D}${nonarch_libdir}/systemd/system-preset
    cat > ${D}${nonarch_libdir}/systemd/system-preset/89-avocado-vt-console.preset <<PRESET
enable getty@.service tty1
PRESET
}

FILES:${PN} = "${nonarch_libdir}/systemd/system-preset/89-avocado-vt-console.preset"
