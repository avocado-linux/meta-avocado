FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI = "git://github.com/rubikpi-ai/prebuilt;protocol=https;branch=BP-BINs \
        file://partition_ufs.xml"
SRCREV = "582e89422b3efd5a09aba3d584beef4083b70d14"

S = "${WORKDIR}/git"

DEPENDS += "unzip-native"

do_extract_bootbin() {
    unzip "${S}/${BOOTBINARIES}.zip" -d "${WORKDIR}"
}

do_extract_bootbin[depends] += "unzip-native:do_populate_sysroot"
addtask extract_bootbin after do_unpack before do_patch

do_patch() {
    install -m 0644 ${WORKDIR}/partition_ufs.xml ${WORKDIR}/${BOOTBINARIES}/
}

do_deploy:append() {
    install -m 0644 ${WORKDIR}/QCM6490_bootbinaries/*.img ${DEPLOYDIR}
}
