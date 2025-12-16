FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
SRC_URI += " \
    file://peridiod.service \
    file://peridiod.env \
"

do_install:append() {
    install -Dm 0644 ${WORKDIR}/peridiod.env ${D}/etc/default/peridiod
}
