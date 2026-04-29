FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

inherit deploy

SRC_URI += "file://disable_uboot.cfg \
    file://rootfs-post.sh \
    file://rootfs-pre.sh"

do_deploy() {
        install -d ${DEPLOYDIR}
        install -m 0755 ${UNPACKDIR}/rootfs-post.sh ${DEPLOYDIR}/
        install -m 0755 ${UNPACKDIR}/rootfs-pre.sh ${DEPLOYDIR}/
}

addtask deploy after do_compile before do_package
