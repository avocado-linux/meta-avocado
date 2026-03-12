FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += "file://avocado-boot.conf \
            file://avocado-loader.conf"

do_install() {
    install -d ${D}/boot
    install -d ${D}/boot/loader
    install -d ${D}/boot/loader/entries

    install -m 0644 ${S}/avocado-loader.conf ${D}/boot/loader/loader.conf
    install -m 0644 ${S}/avocado-boot.conf ${D}/boot/loader/entries/avocado.conf
}

inherit deploy

do_deploy() {
    install -D ${S}/avocado-loader.conf ${DEPLOYDIR}/loader.conf
    install -D ${S}/avocado-boot.conf ${DEPLOYDIR}/avocado.conf
}

addtask deploy after do_install
