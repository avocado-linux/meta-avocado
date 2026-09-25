SUMMARY = "Create the UEFI boot entries avocadoctl's efibootmgr slot action looks up"
DESCRIPTION = "On boot, makes sure the disk systemd-boot was loaded from has one \
UEFI boot entry per A/B boot slot (boot-a, boot-b), pointing at that slot's ESP. \
Provisioning only writes the disk image, so firmware alone never creates them, \
and without them OS-update activation cannot select the target slot. \
Idempotent: NVRAM is written only when an entry is missing or points elsewhere."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = "file://avocado-efi-slot-entries file://avocado-efi-slot-entries.service"
S = "${UNPACKDIR}"

inherit allarch systemd
SYSTEMD_SERVICE:${PN} = "avocado-efi-slot-entries.service"

# flock: the NVRAM lock shared with avocadoctl's efibootmgr slot action.
RDEPENDS:${PN} = "efibootmgr util-linux-flock"

do_install() {
    install -d ${D}${libexecdir}
    install -m 0755 ${UNPACKDIR}/avocado-efi-slot-entries ${D}${libexecdir}/avocado-efi-slot-entries
    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/avocado-efi-slot-entries.service ${D}${systemd_system_unitdir}/
}
