DESCRIPTION = "Grow the /var filesystem to fill its partition on Jetson"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

# The tegraflash layouts give DATAPART_EXPAND allocation_attribute 0x808, so
# the partition takes the rest of the medium. The btrfs written into it is the
# size of its contents and nothing grows it: /var stays near 100 MiB whatever
# the size of the disk.
#
# On the other machines the fstab entry for /var is where a grow would hang,
# but Jetson sets AVOCADO_VAR_PART_DEV = "none" and avocado-tegra-init mounts
# /var from the initramfs, so there is no fstab line to carry
# x-systemd.growfs. systemd-growfs@.service is already in the image and has no
# [Install] section; this pulls in the instance for /var. Growing a filesystem
# that already fills its partition is a no-op, so it is safe on every boot.
do_install() {
    install -d ${D}${systemd_system_unitdir}/local-fs.target.wants
    ln -sf ../systemd-growfs@.service \
        ${D}${systemd_system_unitdir}/local-fs.target.wants/systemd-growfs@var.service
}

FILES:${PN} = "${systemd_system_unitdir}/local-fs.target.wants/systemd-growfs@var.service"
RDEPENDS:${PN} = "systemd"

COMPATIBLE_MACHINE = "(tegra)"
