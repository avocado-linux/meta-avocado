FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

# disable u-boot for nvidia targets
SRC_URI += "file://disable_uboot.cfg"

inherit deploy

# target specific pre/post scripts
SRC_URI += "file://rootfs-post.sh \
    file://rootfs-pre.sh"

do_deploy() {
        install -d ${DEPLOYDIR}
        install -m 0755 ${WORKDIR}/rootfs-post.sh ${DEPLOYDIR}/
        install -m 0755 ${WORKDIR}/rootfs-pre.sh ${DEPLOYDIR}/
}

# make sure we have nvidia boot tools
RDEPENDS:${PN} += "tegra-redundant-boot-base tegra-redundant-boot"

addtask deploy after do_compile before do_package
