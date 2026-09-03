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
"

S = "${UNPACKDIR}"

inherit systemd

SYSTEMD_SERVICE:${PN} = "boot-integrity-report.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

# od(1), for the 5-byte SecureBoot blob, plus sed(1), which the descriptor
# parser needs. Busybox provides both, so on a busybox image these resolve
# either way - but the reporter runs under `set -eu`, so an image WITHOUT them
# does not degrade to `unknown`, it exits before emit() and publishes no record
# at all. That defeats the single-emission invariant the script is built around,
# and the HITL failure ("the reporter did not run") names no cause.
#
# sed became load-bearing when the descriptor moved from being SOURCED to being
# PARSED; the dependency was not updated with it.
RDEPENDS:${PN} = "coreutils sed"

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
#
# The descriptor answers two INDEPENDENT questions and they fail separately:
# how much the variable store is worth (`store_trust`), and where the key
# database came from (`keydb_origin`). Preseeding compiles the key database
# into the U-Boot binary, so it is firmware-resident, while every OTHER
# variable in the same image still lives in the editable file store on the ESP.
# `store_trust=unauthenticated` next to `keydb_origin=firmware-resident` is
# therefore the correct pairing for this change, not a contradiction.
#
# `keydb_origin` is derived from the ARTIFACT, never from the token. The token
# says a build ASKED for enrolment; only the marker the U-Boot recipe writes
# when it has actually staged the seed into $(srctree) says it HAPPENED. A
# descriptor keyed on the token would publish `firmware-resident` about a
# bootloader carrying no seed - exactly the false claim this work exists to
# prevent.
AVOCADO_BOOT_INTEGRITY_POC = "${@bb.utils.contains('DISTRO_FEATURES', 'boot-integrity-poc', '1', '0', d)}"

AVOCADO_BOOT_INTEGRITY_DB_FINGERPRINT = "${DEPLOY_DIR_IMAGE}/sb-keys/db.fingerprint"

# Per-role digests of the DERs gen-efi-seed.sh packed, written beside the seed
# in the same run as the pack. The db entry is the DER digest specifically -
# what the firmware enrols is DER inside an EFI_SIGNATURE_LIST, so a DER hash is
# the one the on-device reporter can compare against the db efivar and a PEM
# hash would never match.
AVOCADO_BOOT_INTEGRITY_SEED_MANIFEST = "${DEPLOY_DIR_IMAGE}/sb-keys/ubootefi.var.manifest"

# Read the marker rather than race it: without this edge the U-Boot deploy may
# not have run when do_install looks, and an absent marker would be
# indistinguishable from a preseed that never happened. Gated on the token so a
# default build's dependency graph is untouched, and routed through
# virtual/bootloader rather than a hardcoded u-boot-imx - this recipe is
# machine-agnostic and each BSP picks its own provider.
do_install[depends] += "${@bb.utils.contains('DISTRO_FEATURES', 'boot-integrity-poc', 'virtual/bootloader:do_deploy', '', d)}"

# sb-keys:do_deploy as well, because the two halves of the provenance claim come
# from two different recipes and only one of them was ordered. db.fingerprint
# (from virtual/bootloader above) is what makes this recipe write
# `keydb_origin=firmware-resident`; ubootefi.var.manifest (from sb-keys) is what
# supplies db.der.sha256, the ONLY thing the device can corroborate that claim
# against. Order one and not the other and a build where the bootloader's deploy
# comes from sstate - so its own do_configure -> sb-keys:do_deploy edge is never
# traversed - ships the claim with no evidence: the device reports
# `keydb_origin=unknown` and the HITL assertion blames the key database rather
# than a build-ordering race.
do_install[depends] += "${@bb.utils.contains('DISTRO_FEATURES', 'boot-integrity-poc', ' sb-keys:do_deploy', '', d)}"

do_install() {
    install -d ${D}${libexecdir}/boot-integrity
    install -m 0755 ${UNPACKDIR}/boot-integrity-report.sh \
        ${D}${libexecdir}/boot-integrity/boot-integrity-report.sh

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/boot-integrity-report.service \
        ${D}${systemd_system_unitdir}/boot-integrity-report.service

    if [ "${AVOCADO_BOOT_INTEGRITY_POC}" = "1" ]; then
        if [ -f "${AVOCADO_BOOT_INTEGRITY_DB_FINGERPRINT}" ]; then
            keydb_origin="firmware-resident"
        else
            keydb_origin="runtime-mutable"
        fi

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
#
# Where the key database came from. This is a SEPARATE question from the line
# above: firmware-resident means PK/KEK/db were compiled into the U-Boot binary
# and cannot be replaced by editing the variable store, which says nothing
# about the other variables kept in that same editable store.
#
# firmware-resident is written only when the U-Boot recipe left its
# db.fingerprint marker in the deploy directory, which it does only after
# actually staging the seed. Token set but marker absent means the preseed did
# not run, and the key database is whatever the mutable store holds.
keydb_origin=$keydb_origin
EOF
        chmod 0644 ${D}${sysconfdir}/avocado/boot-integrity-store

        # The corroboration reference, installed BESIDE the reporter rather than
        # into the descriptor. The descriptor is the file the reporter is not
        # allowed to trust, so an expected value written into it would let one
        # edit change both the claim and the evidence for it - which is no
        # evidence. Keeping them in separate files means a forgery has to alter
        # two things consistently instead of one.
        #
        # Be honest about the ceiling: on this PoC image the rootfs has no
        # verity, so a determined attacker CAN alter both. This does not make
        # keydb_origin unforgeable; it removes the single-file forgery and
        # becomes real protection once the rootfs is verity-backed, which is
        # what the dm-verity work is for. Until then it is defence in depth and
        # is documented as such rather than counted as a control.
        #
        # A hash, not the certificate: the reporter only has to answer "is the
        # enrolled db the one this image shipped", and 64 hex characters answer
        # it without putting a cert on the device or growing the image.
        # Read from the seed manifest, not by hashing the deployed db.der. Both
        # describe a certificate, but only the manifest describes the one that
        # was PACKED into the seed the bootloader compiled - recorded in the
        # same run as the pack. Hashing the live DER here would reintroduce the
        # divergence the manifest exists to remove, and it would do it in the
        # reference the on-device check compares against, so a rotation would
        # make the device report a mismatch it has no way to explain.
        # Fatal on absence, and on a digest that is not usable. Both were silent
        # here while the two OTHER consumers of this same manifest field
        # (u-boot-imx_%.bbappend and avocado-stone.bbappend) bbfatal on exactly
        # these conditions - so one manifest had three readers and only this one
        # would ship a shortfall green.
        #
        # It matters more here than there, because this is the reference the
        # DEVICE compares against: an empty or malformed db.der.sha256 makes
        # corroborate_keydb() return `unknown`, which downgrades keydb_origin and
        # fails the hardware assertion with a message pointing at the key
        # database rather than at this file.
        if [ ! -f "${AVOCADO_BOOT_INTEGRITY_SEED_MANIFEST}" ]; then
            bbfatal "boot-integrity: ${AVOCADO_BOOT_INTEGRITY_SEED_MANIFEST} is absent, so the on-device corroboration reference cannot be installed while this recipe is about to write keydb_origin=firmware-resident. sb-keys' gen-efi-seed.sh writes it beside the seed; this recipe's do_install depends on sb-keys:do_deploy."
        fi
        _bi_digest=$(awk '$1 == "db" { print $2 }' "${AVOCADO_BOOT_INTEGRITY_SEED_MANIFEST}")
        case "$_bi_digest" in
            "" | *[!0-9a-f]*)
                bbfatal "boot-integrity: ${AVOCADO_BOOT_INTEGRITY_SEED_MANIFEST} carries no usable db digest (got '$_bi_digest'), so the reference the device corroborates keydb_origin against would be empty or malformed. Refusing to install it."
                ;;
        esac
        printf '%s\n' "$_bi_digest" > ${D}${libexecdir}/boot-integrity/db.der.sha256
        chmod 0644 ${D}${libexecdir}/boot-integrity/db.der.sha256
    fi
}

FILES:${PN} += " \
    ${libexecdir}/boot-integrity/ \
    ${systemd_system_unitdir}/boot-integrity-report.service \
    ${sysconfdir}/avocado/boot-integrity-store \
"
