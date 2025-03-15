FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:qemux86-64 += "file://avocado-boot.conf \
            file://avocado-loader.conf"

do_install:qemux86-64() {
    install -d ${D}/boot
    install -d ${D}/boot/loader
    install -d ${D}/boot/loader/entries

    install -m 0644 ${S}/avocado-loader.conf ${D}/boot/loader/loader.conf
    install -m 0644 ${S}/avocado-boot.conf ${D}/boot/loader/entries/avocado-boot.conf
}

inherit deploy

do_deploy() {
    if [ -f ${S}/avocado-boot.conf ]; then
        install -D ${S}/avocado-boot.conf ${DEPLOYDIR}/boot.conf
    fi
}

addtask deploy after do_install
