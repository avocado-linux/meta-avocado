SUMMARY = "LUKS2 /var unlock and first-boot-format script"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://cryptsetup-var.sh \
    file://var-key.sh \
    file://cryptsetup-var.service \
    file://99-zz-cryptsetup-var.rules \
    file://avocado-posture-publish.sh \
    file://avocado-posture-publish.service \
"

# Tools cryptsetup-var.sh + var-key.sh invoke in the (minimal) initramfs:
#   cryptsetup    - luksFormat / open / resize
#   openssl-bin   - var-key.sh derives the phase-1 key via `openssl kdf ARGON2ID`
#                   (libcrypto is already present via systemd; this adds the CLI)
#   btrfs-tools   - mkfs.btrfs on first boot (the filesystem is grown at mount
#                   time via x-systemd.growfs, not here)
#   gawk          - awk in the cpuinfo-serial lookup and the dm resize check
#   sed           - strips the `openssl dgst` prefix when deriving the salt
#   libdevmapper  - provides dmsetup, used by maybe_resize's data-offset
#                   query. Not actually in the initramfs otherwise: nothing
#                   else RDEPENDS on it, unlike blockdev/blkid (util-linux)
#                   and systemd-cryptenroll (systemd), which genuinely are
#                   already there via packagegroup-avocado-initramfs.
#                   The package is libdevmapper, NOT device-mapper: dmsetup
#                   ships in meta-oe lvm2's own `PACKAGES =+ "libdevmapper"`
#                   split (FILES:libdevmapper carries ${sbindir}/dmsetup).
#                   `device-mapper` is what other distros call it and nothing
#                   in this layer set RPROVIDES that name, so asking for it
#                   fails dependency resolution rather than pulling in dmsetup.
# (blockdev, blkid, systemd-cryptenroll, mktemp, dirname, tr, cut are already
#  in the avocado initramfs.)
RDEPENDS:${PN} = "cryptsetup openssl-bin btrfs-tools gawk sed libdevmapper"

inherit systemd

SYSTEMD_SERVICE:${PN} = "cryptsetup-var.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

S = "${UNPACKDIR}"

do_install() {
    install -d ${D}${libexecdir}/cryptsetup-var
    install -m 0750 ${UNPACKDIR}/cryptsetup-var.sh ${D}${libexecdir}/cryptsetup-var/
    install -m 0750 ${UNPACKDIR}/var-key.sh ${D}${libexecdir}/cryptsetup-var/

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/cryptsetup-var.service ${D}${systemd_system_unitdir}/

    # Statically enable the unit for the initrd. SYSTEMD_AUTO_ENABLE relies on
    # the preset being applied at image time, but the initramfs rootfs build
    # does not enable a WantedBy=initrd-root-fs.target unit there, so the
    # .wants symlink is never created and /var unlock never runs (boot drops to
    # emergency mode). Stage the symlink by hand so the service is pulled into
    # the initrd regardless of preset handling.
    install -d ${D}${systemd_system_unitdir}/initrd-root-fs.target.wants
    ln -sf ../cryptsetup-var.service \
        ${D}${systemd_system_unitdir}/initrd-root-fs.target.wants/cryptsetup-var.service

    # udev rule that re-creates /dev/mapper/var in the real root (the device is
    # opened in the initrd; see the rule for why the rootfs coldplug otherwise
    # drops it). Shipped in its own package so it can be installed into the
    # rootfs - the rest of cryptsetup-var is initramfs-only.
    install -d ${D}${nonarch_base_libdir}/udev/rules.d
    install -m 0644 ${UNPACKDIR}/99-zz-cryptsetup-var.rules \
        ${D}${nonarch_base_libdir}/udev/rules.d/99-zz-cryptsetup-var.rules

    # Posture publisher: reads what cryptsetup-var.sh left in /run and puts it in
    # the U-Boot KV store, which is what peridiod already reads.
    install -m 0750 ${UNPACKDIR}/avocado-posture-publish.sh \
        ${D}${libexecdir}/cryptsetup-var/
    install -m 0644 ${UNPACKDIR}/avocado-posture-publish.service \
        ${D}${systemd_system_unitdir}/
}

PACKAGES =+ "${PN}-udev ${PN}-posture"
FILES:${PN}-udev = "${nonarch_base_libdir}/udev/rules.d/99-zz-cryptsetup-var.rules"

# Posture publishing is rootfs-only, so it gets its own package rather than
# riding along in ${PN} and being pulled into the initrd - it reads what the
# initramfs recorded, it does not run there.
#
# The split relies on PACKAGES order, which is load-bearing here: FILES:${PN}
# below globs the whole ${libexecdir}/cryptsetup-var/ directory and so also
# matches this script, and the first package in PACKAGES to match a file claims
# it. `PACKAGES =+` prepends, putting ${PN}-posture ahead of ${PN}, so the script
# lands here rather than in the initramfs package. Switching that to `=.` or
# appending instead would silently pull the publisher into the initrd.
#
# libubootenv supplies fw_printenv/fw_setenv and util-linux-findmnt supplies
# findmnt. Both are RDEPENDS rather than optional probes because a posture
# reporter that silently cannot read posture is worse than one that fails to
# install; the script still degrades cleanly if the fw_env.config a given
# machine needs was never generated.
FILES:${PN}-posture = " \
    ${libexecdir}/cryptsetup-var/avocado-posture-publish.sh \
    ${systemd_system_unitdir}/avocado-posture-publish.service \
"
RDEPENDS:${PN}-posture = "libubootenv util-linux-findmnt"
SYSTEMD_SERVICE:${PN}-posture = "avocado-posture-publish.service"
SYSTEMD_AUTO_ENABLE:${PN}-posture = "enable"

FILES:${PN} += "${libexecdir}/cryptsetup-var/"
FILES:${PN} += "${systemd_system_unitdir}/cryptsetup-var.service"
FILES:${PN} += "${systemd_system_unitdir}/initrd-root-fs.target.wants/cryptsetup-var.service"
