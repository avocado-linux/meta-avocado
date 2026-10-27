DESCRIPTION = "Generate fw_env.config at boot for the disk the system booted from"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

# Same contract as meta-avocado-nxp's recipe of this name (the
# /run/avocado/fw_env.config that libubootenv's /etc/fw_env.config points
# at), with this layer's env offsets and a root-disk lookup that works for
# root=PARTLABEL=.
SRC_URI = "file://avocado-uboot-env \
           file://avocado-uboot-env.service"

S = "${UNPACKDIR}"

inherit systemd

do_install() {
    install -d ${D}${sbindir}
    install -m 0755 ${UNPACKDIR}/avocado-uboot-env ${D}${sbindir}/avocado-uboot-env

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/avocado-uboot-env.service \
        ${D}${systemd_system_unitdir}/avocado-uboot-env.service
}

SYSTEMD_SERVICE:${PN} = "avocado-uboot-env.service"
SYSTEMD_AUTO_ENABLE = "enable"

RDEPENDS:${PN} = "util-linux-findmnt util-linux-lsblk"

FILES:${PN} = "${sbindir}/avocado-uboot-env \
               ${systemd_system_unitdir}/avocado-uboot-env.service"
