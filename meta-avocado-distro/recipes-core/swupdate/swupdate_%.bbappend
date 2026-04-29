FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI += "file://swupdate.cfg"

do_install:append() {
    install -m 0644 ${UNPACKDIR}/swupdate.cfg ${D}${sysconfdir}/swupdate.cfg
    echo "${MACHINE_SHORT_NAME} ${DISTRO_VERSION}" >> ${D}${sysconfdir}/hwrevision
}
