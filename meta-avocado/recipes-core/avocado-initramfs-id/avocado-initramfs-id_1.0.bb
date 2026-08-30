SUMMARY = "Publish the running initramfs build id to /run from the initramfs"
DESCRIPTION = "Reads AVOCADO_OS_BUILD_ID from the initramfs release files and writes it to \
/run/avocado/initramfs-build-id before switch-root. /run survives the handover, so the booted \
system can compare the target initramfs against what is actually running rather than against the \
previous runtime manifest's record of it - which is absent on older runtimes and cannot be \
trusted after an A/B rollback."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://avocado-initramfs-id file://avocado-initramfs-id.service"
S = "${UNPACKDIR}"

# sed and printf only, from busybox or coreutils - both already in every
# initramfs, so this adds no runtime dependency of its own.

inherit systemd
SYSTEMD_SERVICE:${PN} = "avocado-initramfs-id.service"

do_install() {
    install -d ${D}${libexecdir}
    install -m 0755 ${UNPACKDIR}/avocado-initramfs-id ${D}${libexecdir}/avocado-initramfs-id
    install -d ${D}${systemd_system_unitdir}/initrd.target.wants
    install -m 0644 ${UNPACKDIR}/avocado-initramfs-id.service ${D}${systemd_system_unitdir}/
    # Same as cryptsetup-var and avocado-var-grow: the initramfs image applies
    # no preset for initrd units, so stage the .wants symlink by hand.
    ln -sf ../avocado-initramfs-id.service ${D}${systemd_system_unitdir}/initrd.target.wants/avocado-initramfs-id.service
}

FILES:${PN} += "${systemd_system_unitdir}/initrd.target.wants/avocado-initramfs-id.service"
