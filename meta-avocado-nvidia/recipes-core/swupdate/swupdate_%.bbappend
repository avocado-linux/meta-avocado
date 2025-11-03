FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

# disable u-boot for nvidia targets
SRC_URI += "file://disable_uboot.cfg"

inherit deploy

# target specific pre/post scripts
SRC_URI += "file://ext-post.sh \
    file://kernel-post.sh \
    file://kernel-pre.sh \
    file://rootfs-post.sh \
    file://rootfs-pre.sh"

do_deploy() {
        install -d ${DEPLOYDIR}
        install -m 0755 ${WORKDIR}/ext-post.sh ${DEPLOYDIR}/
        install -m 0755 ${WORKDIR}/kernel-post.sh ${DEPLOYDIR}/
        install -m 0755 ${WORKDIR}/kernel-pre.sh ${DEPLOYDIR}/
        install -m 0755 ${WORKDIR}/rootfs-post.sh ${DEPLOYDIR}/
        install -m 0755 ${WORKDIR}/rootfs-pre.sh ${DEPLOYDIR}/
}

# make sure we have nvbootctrl
RDEPENDS:${PN} += "tegra-redundant-boot-base"

addtask deploy after do_compile before do_package