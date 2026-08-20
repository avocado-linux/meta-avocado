SUMMARY = "Initrd bring-up of the OP-TEE fTPM (tee-supplicant + tpm_ftpm_tee)"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

# fTPM seal persistence across reboot needs RPMB (a hardware-backed rollback
# counter). On real ARM eMMC hardware this is present and the TPM2 PCR-7 seal on
# /var reopens on every subsequent boot. Under qemuarm64 (the QEMU 'virt'
# machine) there is NO RPMB: OP-TEE cannot commit its secure-storage anti-
# rollback counter ("Failed to commit dirh counter" / "using 0" on the secure
# console), so it will not trust the fTPM's saved state on the next boot and the
# fTPM re-derives its seed. The result on QEMU: the seal is created and used on
# first boot, but on reboot /var falls back to its Argon2id keyslot (still fully
# encrypted, just not TPM-bound that boot). This is a QEMU limitation, not a
# defect in this layer; the /var/lib/tee store below is nonetheless persisted on
# the recovery partition so the mechanism is exercised end to end.
#
# To demonstrate reboot-survival under QEMU one would additionally set
# CFG_RPMB_FS=y in optee-os and make tee-supplicant's RPMB emulator (RPMB_EMU=1,
# currently RAM-only) file-backed on that persistent store. Not done here on
# purpose: it only matters for the emulator, and hardware already works.

SRC_URI = " \
    file://optee-ftpm-setup.sh \
    file://optee-ftpm-setup.service \
    file://optee-ftpm.conf \
"

# tee-supplicant (optee-client) services the fTPM REE-FS; the fTPM driver is a
# module (see ftpm.cfg); mkfs.btrfs/mount for the persistent TEE store are
# already in the initramfs via cryptsetup-var.
RDEPENDS:${PN} = "optee-client kernel-module-tpm-ftpm-tee"

inherit systemd

SYSTEMD_SERVICE:${PN} = "optee-ftpm-setup.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

S = "${UNPACKDIR}"

do_install() {
    install -d ${D}${libexecdir}/optee-ftpm
    install -m 0750 ${UNPACKDIR}/optee-ftpm-setup.sh ${D}${libexecdir}/optee-ftpm/

    install -d ${D}${nonarch_base_libdir}/modprobe.d
    install -m 0644 ${UNPACKDIR}/optee-ftpm.conf ${D}${nonarch_base_libdir}/modprobe.d/

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/optee-ftpm-setup.service ${D}${systemd_system_unitdir}/

    # Statically enable for the initrd (the initramfs build does not apply the
    # preset for a WantedBy=initrd-root-fs.target unit - same as cryptsetup-var).
    install -d ${D}${systemd_system_unitdir}/initrd-root-fs.target.wants
    ln -sf ../optee-ftpm-setup.service \
        ${D}${systemd_system_unitdir}/initrd-root-fs.target.wants/optee-ftpm-setup.service
}

FILES:${PN} += "${libexecdir}/optee-ftpm/"
FILES:${PN} += "${nonarch_base_libdir}/modprobe.d/optee-ftpm.conf"
FILES:${PN} += "${systemd_system_unitdir}/optee-ftpm-setup.service"
FILES:${PN} += "${systemd_system_unitdir}/initrd-root-fs.target.wants/optee-ftpm-setup.service"

# Only the OP-TEE fTPM machines need this.
COMPATIBLE_MACHINE = "avocado-qemuarm64"

# Assert this recipe's COMPATIBLE_MACHINE agrees with the machine's own
# AVOCADO_SECURITY_CAPABILITIES declaration, rather than letting the two drift
# apart silently - the class of defect avocado-security-capabilities.bbclass
# exists to close.
#
# devtool-debt: this catches only ONE of the two directions a disagreement can
# take. It runs in an anonymous python function, which BitBake only executes
# for a MACHINE this recipe's own COMPATIBLE_MACHINE already matches - a
# machine COMPATIBLE_MACHINE excludes never reaches this code at all, so
# "declaration claims ftpm, but this recipe excludes the machine" cannot be
# caught here; nothing from an excluded recipe ever runs to report it. Only
# "this recipe would build ftpm, but the declaration forgot to say so" is
# checked. Closing the other direction needs either this recipe's
# COMPATIBLE_MACHINE value duplicated into a machine-wide config-level check
# (defeating the "declared in exactly one place" premise this whole change
# exists for) or COMPATIBLE_MACHINE generated FROM the declaration (design.md's
# deferred, unverified idea). Ceiling: the declaration-excludes-but-recipe-
# includes direction stays uncaught. Upgrade trigger: COMPATIBLE_MACHINE
# becomes derivable from AVOCADO_SECURITY_CAPABILITIES, or a second check is
# added elsewhere for that direction specifically.
python () {
    machine = d.getVar("MACHINE") or "<unknown>"
    capabilities = (d.getVar("AVOCADO_SECURITY_CAPABILITIES") or "").split()
    if "ftpm" not in capabilities:
        bb.fatal(
            "machine %s can build optee-ftpm-init (COMPATIBLE_MACHINE "
            "matches) but its AVOCADO_SECURITY_CAPABILITIES declaration does "
            "not include ftpm. Unmet prerequisite: add ftpm to "
            "AVOCADO_SECURITY_CAPABILITIES in this machine's conf, or this "
            "recipe's COMPATIBLE_MACHINE no longer applies to it."
            % machine
        )
}
