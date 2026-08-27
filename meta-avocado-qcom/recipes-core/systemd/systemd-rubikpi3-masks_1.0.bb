SUMMARY = "Avocado-rubikpi3 systemd preset overrides + masks for unused features"
DESCRIPTION = "Avocado boots via the Qualcomm XBL/ABL chain (not systemd-boot), \
ships a read-only erofs rootfs, doesn't run NFSD, and uses a serial console \
(no tty1). Override / mask the systemd units whose features avocado \
intentionally doesn't use, so they don't fail at every boot. Users can \
override or unmask on /var-overlay to revert."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

inherit features_check
REQUIRED_DISTRO_FEATURES = "systemd"

# Per-machine packaging — the choices reflect the rubikpi3 partition layout
# and the qcom-XBL/ABL boot chain.
PACKAGE_ARCH = "${MACHINE_ARCH}"
ALLOW_EMPTY:${PN} = "1"

do_install() {
    install -d ${D}${nonarch_libdir}/systemd/system-preset
    install -d ${D}${sysconfdir}/systemd/system

    # Beat upstream OE-core's `/lib/systemd/system-preset/90-systemd.preset`,
    # which has `enable getty@.service`. systemd resolves that to the default
    # instance (`getty@tty1.service`), but rubikpi3 has no virtual console,
    # so agetty fails to open /dev/tty1 (status 208/STDIN). Our serial console
    # is brought up by `serial-getty@ttyMSM0.service` via systemd-getty-
    # generator, which doesn't depend on this preset.
    # Presets are first-match-wins by lexicographic order, so `89-` beats `90-`.
    cat > ${D}${nonarch_libdir}/systemd/system-preset/89-avocado-rubikpi3.preset <<EOF
disable getty@.service
EOF

    # The preset above only steers future `systemctl preset` runs; it cannot
    # undo an enablement that already happened. systemd runs preset-all on
    # first boot, before avocado merges the extension that carries this
    # package, so getty@.service gets enabled anyway and the resulting
    # /etc/systemd/system/getty.target.wants/getty@.service persists on the
    # writable /etc layer -- observed on hardware as getty@getty.service
    # failing a start-limit hit and holding systemd in `degraded` even with the
    # preset installed. Masking the template covers that: instances of a masked
    # template are masked, so the stale wants symlink resolves to nothing.
    # Nothing on this board wants a virtual-console getty; the serial console
    # is serial-getty@ttyMSM0 via systemd-getty-generator.
    ln -sf /dev/null ${D}${sysconfdir}/systemd/system/getty@.service

    # systemd-gpt-auto-generator picks up the rubikpi3 EFI partition by its
    # GPT type GUID (C12A7328-...) and creates boot.mount/boot.automount.
    # Avocado's RO erofs rootfs doesn't need /boot mounted, and the qcom
    # bootloader chain has already finished loading the kernel by the time
    # systemd starts. Mask via /etc symlink (highest precedence).
    ln -sf /dev/null ${D}${sysconfdir}/systemd/system/boot.mount
    ln -sf /dev/null ${D}${sysconfdir}/systemd/system/boot.automount

    # systemd-boot self-update / random-seed services target the ESP via
    # boot.mount; not applicable when boot is via qcom XBL/ABL.
    ln -sf /dev/null ${D}${sysconfdir}/systemd/system/systemd-boot-update.service
    ln -sf /dev/null ${D}${sysconfdir}/systemd/system/systemd-boot-random-seed.service

    # NFSD configfs mount — avocado doesn't ship NFSD on rubikpi3 by default.
    ln -sf /dev/null ${D}${sysconfdir}/systemd/system/proc-fs-nfsd.mount
}

FILES:${PN} = " \
    ${nonarch_libdir}/systemd/system-preset/89-avocado-rubikpi3.preset \
    ${sysconfdir}/systemd/system \
"
