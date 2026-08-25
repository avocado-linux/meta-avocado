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
# module (see ftpm.cfg).
#
# btrfs-tools is named here rather than assumed. optee-ftpm-setup formats its
# persistent TEE store with mkfs.btrfs, and an earlier revision of this line
# left it out on the grounds that the tool "is already in the initramfs via
# cryptsetup-var" - true only when the encrypted-var DISTRO_FEATURE is on,
# since that is what pulls cryptsetup-var in. Build the fTPM without it, which
# kas/feature/ftpm.yml invites by being independently selectable, and the tool
# is absent: the format fails, the script takes its skip path, and no TPM
# appears. Confirmed on avocado-imx93-frdm with an ftpm-but-not-encrypted-var
# image, where the console read "could not prepare persistent TEE store" while
# systemd reported the unit Finished - so journalctl showed a healthy service
# and /dev/tpm0 was simply never there.
RDEPENDS:${PN} = "optee-client kernel-module-tpm-ftpm-tee btrfs-tools"

inherit systemd

SYSTEMD_SERVICE:${PN} = "optee-ftpm-setup.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

S = "${UNPACKDIR}"

do_install() {
    install -d ${D}${libexecdir}/optee-ftpm
    install -m 0750 ${UNPACKDIR}/optee-ftpm-setup.sh ${D}${libexecdir}/optee-ftpm/
    sed -i -e 's|@TEE_STORE_DEV@|${OPTEE_FTPM_TEE_STORE_DEV}|g' \
        ${D}${libexecdir}/optee-ftpm/optee-ftpm-setup.sh

    install -d ${D}${nonarch_base_libdir}/modprobe.d
    install -m 0644 ${UNPACKDIR}/optee-ftpm.conf ${D}${nonarch_base_libdir}/modprobe.d/

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/optee-ftpm-setup.service ${D}${systemd_system_unitdir}/
    sed -i -e 's|@TEE_STORE_DEV@|${OPTEE_FTPM_TEE_STORE_DEV}|g' \
           -e 's|@TEE_STORE_UNIT@|${OPTEE_FTPM_TEE_STORE_UNIT}|g' \
        ${D}${systemd_system_unitdir}/optee-ftpm-setup.service

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
# `tegra` is the MACHINEOVERRIDE every meta-tegra machine carries, so this
# matches all Avocado Jetson machines at once (they set OPTEE_ENABLE_FTPM).
COMPATIBLE_MACHINE = "avocado-qemuarm64|avocado-imx93-frdm|tegra"

# Block device holding the persistent REE-FS TEE store (/var/lib/tee). A
# machine fact: a small, otherwise-unused GPT partition outside the encrypted
# /var. The generic default is the recovery partition (qemuarm64, imx93-frdm);
# Jetson overrides it in avocado-jetson.inc because its `recovery` partition
# holds a kernel image. Substituted into the script and unit at install time.
OPTEE_FTPM_TEE_STORE_DEV ?= "/dev/disk/by-partlabel/recovery"
# systemd unit name for that path (e.g. dev-disk-by\x2dpartlabel-recovery.device).
# The dash escape is doubled ('\\x2d' -> two backslashes) because the value
# is fed to a GNU sed replacement in do_install, which would otherwise read
# \x2d as a hex escape and emit a plain '-', silently un-escaping the unit.
OPTEE_FTPM_TEE_STORE_UNIT = "${@d.getVar('OPTEE_FTPM_TEE_STORE_DEV').lstrip('/').replace('-', '\\\\x2d').replace('/', '-')}.device"

# Assert the machine's AVOCADO_SECURITY_CAPABILITIES declaration agrees with
# whether the fTPM is actually being built in, rather than letting the two drift
# apart silently - the class of defect avocado-security-capabilities.bbclass
# exists to close.
#
# Gated on MACHINE_FEATURES rather than on COMPATIBLE_MACHINE matching, which is
# what an earlier revision keyed on. COMPATIBLE_MACHINE now names
# avocado-imx93-frdm unconditionally, but the capability on that board is real
# only when kas/feature/ftpm.yml has put meta-arm in the layer set and appended
# optee-ftpm to MACHINE_FEATURES - without it there is no TA for OP-TEE to
# advertise. Keying on the match therefore fired on every DEFAULT imx93 build,
# where the declaration correctly omits ftpm, and failed the parse outright.
#
# devtool-debt: this catches only ONE of the two directions a disagreement can
# take - "the feature is on but the declaration forgot to say so". The reverse,
# "the declaration claims ftpm but nothing builds it", is not caught here:
# an anonymous python function runs only for a machine this recipe's own
# COMPATIBLE_MACHINE already matches, so a machine the recipe excludes never
# reaches this code to be reported on. Ceiling: the
# declaration-claims-but-nothing-builds direction stays uncaught. Upgrade
# trigger: COMPATIBLE_MACHINE becomes derivable from
# AVOCADO_SECURITY_CAPABILITIES, or a config-level check covers that direction.
python () {
    features = (d.getVar("MACHINE_FEATURES") or "").split()
    if "optee-ftpm" not in features:
        return
    machine = d.getVar("MACHINE") or "<unknown>"
    capabilities = (d.getVar("AVOCADO_SECURITY_CAPABILITIES") or "").split()
    if "ftpm" not in capabilities:
        bb.fatal(
            "machine %s carries optee-ftpm in MACHINE_FEATURES, so this build "
            "installs the fTPM, but its AVOCADO_SECURITY_CAPABILITIES "
            "declaration does not include ftpm. Unmet prerequisite: add ftpm to "
            "AVOCADO_SECURITY_CAPABILITIES in this machine's conf, or drop "
            "optee-ftpm from MACHINE_FEATURES."
            % machine
        )
}
