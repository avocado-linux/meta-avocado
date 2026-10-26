FILESEXTRAPATHS:prepend:arm64-uefi := "${THISDIR}/files:"

SRC_URI:append:arm64-uefi = " file://avocado-boot.conf file://avocado-loader.conf"

do_install:arm64-uefi() {
    install -d ${D}/boot/loader/entries
    install -m 0644 ${S}/avocado-loader.conf ${D}/boot/loader/loader.conf
    install -m 0644 ${S}/avocado-boot.conf ${D}/boot/loader/entries/avocado.conf
}

inherit deploy

do_deploy() {
    :
}

do_deploy:arm64-uefi() {
    install -D ${S}/avocado-loader.conf ${DEPLOYDIR}/loader.conf
    install -D ${S}/avocado-boot.conf ${DEPLOYDIR}/avocado.conf
}

addtask deploy after do_install
