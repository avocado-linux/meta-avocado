SUMMARY = "Publish boot-integrity state to userspace"
DESCRIPTION = "Reports what the firmware enforced and whether anything vouches \
for the firmware reporting it, as one record in /run and in the journal."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

# The script and unit sit beside this recipe rather than in a files/ subdir.
# Default FILESPATH covers ${THISDIR}/${PN} and ${THISDIR}/files but NOT
# ${THISDIR} itself, so without this do_fetch fails with "Unable to find file"
# naming a path that is plainly there.
FILESEXTRAPATHS:prepend := "${THISDIR}:"

SRC_URI = " \
    file://boot-integrity-report.sh \
    file://boot-integrity-report.service \
    file://sys-firmware-efi-efivars.mount \
"

S = "${UNPACKDIR}"

inherit systemd

# Both units are enabled: the mount is what makes efivarfs readable at all on
# this image, and it is condition-guarded so it is inert where efivarfs does not
# exist.
SYSTEMD_SERVICE:${PN} = "boot-integrity-report.service sys-firmware-efi-efivars.mount"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

# od(1), for the 5-byte SecureBoot blob. coreutils on a normal image, but busybox
# also provides it, so this is RDEPENDS on the command rather than the package.
RDEPENDS:${PN} = "coreutils"

# The store descriptor records how much the variable store itself is worth,
# which the script cannot determine at runtime: nothing in efivarfs says whether
# the firmware behind it kept the variables somewhere tamper-resistant or in a
# file on a FAT partition.
#
# Written ONLY for boot-integrity-poc, and only ever with the pessimistic value.
# There is deliberately no branch here that writes `authenticated`: the real
# capability needs an authenticated store this layer does not yet build, and a
# recipe that could emit that string is one edit away from emitting it wrongly.
# A build without the token installs no descriptor and the script reports
# `unknown`, which is correct - an unknown store is not a trusted one.
AVOCADO_BOOT_INTEGRITY_POC = "${@bb.utils.contains('DISTRO_FEATURES', 'boot-integrity-poc', '1', '0', d)}"

do_install() {
    install -d ${D}${libexecdir}/boot-integrity
    install -m 0755 ${UNPACKDIR}/boot-integrity-report.sh \
        ${D}${libexecdir}/boot-integrity/boot-integrity-report.sh

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/boot-integrity-report.service \
        ${D}${systemd_system_unitdir}/boot-integrity-report.service
    install -m 0644 ${UNPACKDIR}/sys-firmware-efi-efivars.mount \
        ${D}${systemd_system_unitdir}/sys-firmware-efi-efivars.mount

    if [ "${AVOCADO_BOOT_INTEGRITY_POC}" = "1" ]; then
        install -d ${D}${sysconfdir}/avocado
        cat > ${D}${sysconfdir}/avocado/boot-integrity-store <<EOF
# Written by boot-integrity.bb because this image was built with the
# boot-integrity-poc DISTRO_FEATURE.
#
# The PoC keeps UEFI variables in /ubootefi.var on the EFI system partition, a
# FAT filesystem that anyone able to write the boot medium can edit. Variables
# therefore PERSIST across a reboot without RESISTING anything, and a value seen
# surviving one must not be read as having withstood tampering.
store_trust=unauthenticated
EOF
        chmod 0644 ${D}${sysconfdir}/avocado/boot-integrity-store
    fi
}

FILES:${PN} += " \
    ${libexecdir}/boot-integrity/ \
    ${systemd_system_unitdir}/boot-integrity-report.service \
    ${systemd_system_unitdir}/sys-firmware-efi-efivars.mount \
    ${sysconfdir}/avocado/boot-integrity-store \
"
