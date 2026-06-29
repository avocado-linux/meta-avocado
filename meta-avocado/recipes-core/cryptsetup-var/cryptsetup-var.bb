SUMMARY = "LUKS2 /var unlock and first-boot-format script"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://cryptsetup-var.sh \
    file://var-key.sh \
    file://cryptsetup-var.service \
"

# Tools cryptsetup-var.sh + var-key.sh invoke in the (minimal) initramfs:
#   cryptsetup    - luksFormat / open / resize
#   openssl-bin   - var-key.sh derives the phase-1 key via `openssl kdf ARGON2ID`
#                   (libcrypto is already present via systemd; this adds the CLI)
#   btrfs-tools   - mkfs.btrfs on first boot + `btrfs filesystem resize`
#   gawk          - awk in the cpuinfo-serial lookup and the dm resize check
#   sed           - strips the `openssl dgst` prefix when deriving the salt
# (blockdev, dmsetup, systemd-cryptenroll, mktemp, dirname, tr, cut are already
#  in the avocado initramfs.)
RDEPENDS:${PN} = "cryptsetup openssl-bin btrfs-tools gawk sed"

inherit systemd

SYSTEMD_SERVICE:${PN} = "cryptsetup-var.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

S = "${WORKDIR}"

do_install() {
    install -d ${D}${libexecdir}/cryptsetup-var
    install -m 0750 ${WORKDIR}/cryptsetup-var.sh ${D}${libexecdir}/cryptsetup-var/
    install -m 0750 ${WORKDIR}/var-key.sh ${D}${libexecdir}/cryptsetup-var/

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${WORKDIR}/cryptsetup-var.service ${D}${systemd_system_unitdir}/
}

FILES:${PN} += "${libexecdir}/cryptsetup-var/"
FILES:${PN} += "${systemd_system_unitdir}/cryptsetup-var.service"
