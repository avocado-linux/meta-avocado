SUMMARY = "Initrd bring-up of the OP-TEE fTPM (tee-supplicant + tpm_ftpm_tee)"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

# fTPM seal persistence across reboot needs RPMB, a rollback counter the
# storage itself enforces. Neither machine here has it in play today, for
# different reasons, and the shared consequence is the same: the seal is
# created and used on first boot, and on reboot /var falls back to its Argon2id
# keyslot - still fully encrypted, just not TPM-bound that boot.
#
# qemuarm64 (the QEMU 'virt' machine) has no RPMB at all. OP-TEE cannot commit
# its secure-storage anti-rollback counter ("Failed to commit dirh counter" /
# "using 0" on the secure console), so it will not trust the fTPM's saved state
# next boot and the fTPM re-derives its seed.
#
# avocado-imx93-frdm does have RPMB in hardware - it is eMMC - but having the
# hardware is not the same as using it: OP-TEE only talks to RPMB when built
# with CFG_RPMB_FS=y, and the i.MX93 OP-TEE is not. The one place the tree sets
# it (meta-imx's stmm-imx optee-os bbappend) is gated on a MACHINE_FEATURE
# nothing here enables, and it pairs CFG_RPMB_WRITE_KEY=y with
# CFG_RPMB_TESTKEY=y - which would program the eMMC's one-time authentication
# key to a publicly known value. So RPMB is deliberately a separate, explicitly
# confirmed step rather than something a build turns on; see kas/feature/ftpm.yml.
#
# Until then the /var/lib/tee store below is persisted on the recovery partition
# on both machines, so the mechanism is exercised end to end.

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

# Only the OP-TEE fTPM machines need this. Lives in the shared layer rather
# than meta-avocado-qemu because an i.MX93 build never parses that layer - its
# kas machine config pulls base + nxp + freescale only - while the initramfs
# packagegroup that pulls this recipe in (on MACHINE_FEATURES optee-ftpm) is
# shared and would otherwise RDEPEND on a recipe with no provider.
COMPATIBLE_MACHINE = "avocado-qemuarm64|avocado-imx93-frdm"
