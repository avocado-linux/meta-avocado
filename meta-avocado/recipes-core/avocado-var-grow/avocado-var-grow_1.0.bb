SUMMARY = "Grow the var partition to its disk in the initramfs, when provisioning marked it"
DESCRIPTION = "Reads GPT attribute bit 56 on the var partition (set by stone/fwup from the \
manifest's expand: true) and extends the partition to the end of the disk before \
cryptsetup-var opens it or var.mount mounts it. Idempotent from the partition table alone."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://avocado-var-grow file://avocado-var-grow.service"
S = "${UNPACKDIR}"

# sgdisk (gptfdisk), partx and blkid (util-linux); util-linux is already in the
# initramfs, gptfdisk is what this recipe adds.
RDEPENDS:${PN} = "gptfdisk util-linux-partx util-linux-blkid"

inherit systemd
SYSTEMD_SERVICE:${PN} = "avocado-var-grow.service"

do_install() {
    install -d ${D}${libexecdir}
    install -m 0755 ${UNPACKDIR}/avocado-var-grow ${D}${libexecdir}/avocado-var-grow
    install -d ${D}${systemd_system_unitdir}/initrd-root-fs.target.wants
    install -m 0644 ${UNPACKDIR}/avocado-var-grow.service ${D}${systemd_system_unitdir}/
    # Same as cryptsetup-var: the initramfs image applies no preset for
    # initrd-root-fs.target units, so stage the .wants symlink by hand.
    ln -sf ../avocado-var-grow.service ${D}${systemd_system_unitdir}/initrd-root-fs.target.wants/avocado-var-grow.service
}

FILES:${PN} += "${systemd_system_unitdir}/initrd-root-fs.target.wants/avocado-var-grow.service"
