FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
SRC_URI:append = "file://zram-generator.conf"

do_install:append () {
        install -m 0644 ${WORKDIR}/zram-generator.conf ${D}${sysconfdir}/systemd/
}
