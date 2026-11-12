SUMMARY = "Avocado Jetson systemd preset overrides"
DESCRIPTION = "Jetson devkits expose their console on the Tegra Combined UART \
(ttyTCU0) and have no virtual console. Override the systemd presets whose \
units cannot succeed on such a board, so they do not fail at every boot. \
Users can override or unmask on /var-overlay to revert."
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

inherit features_check
REQUIRED_DISTRO_FEATURES = "systemd"

PACKAGE_ARCH = "${MACHINE_ARCH}"

do_install() {
    install -d ${D}${nonarch_libdir}/systemd/system-preset

    # Beat upstream OE-core's `/lib/systemd/system-preset/90-systemd.preset`,
    # which has `enable getty@.service`. That is a template with no instance,
    # so the offline enabler writes a bare `getty@.service` symlink into
    # getty.target.wants and systemd instantiates it as `getty@getty.service`
    # -- agetty then tries to open /dev/getty, exits 208/STDIN, hits the
    # restart limit and leaves the system `degraded` on every boot.
    #
    # Observed on a jetson-orin-nano built from the edge channel:
    #
    #   × getty@getty.service - Getty on getty
    #     Process: ExecStart=/usr/sbin/agetty ... (code=exited, status=208/STDIN)
    #
    # The real console is brought up by `serial-getty@ttyTCU0.service` via
    # systemd-getty-generator, which reads SERIAL_CONSOLES and does not depend
    # on this preset -- so disabling the VT getty costs nothing.
    #
    # Presets are first-match-wins in lexicographic order, so `89-` beats `90-`.
    # Same fix, same failure mode as meta-avocado-qcom's
    # systemd-rubikpi3-masks (which resolves to getty@tty1 rather than
    # getty@getty, the instance differing only by how the empty template
    # instance got filled in).
    cat > ${D}${nonarch_libdir}/systemd/system-preset/89-avocado-jetson.preset <<EOF
disable getty@.service
EOF

    # Every Jetson builds the OP-TEE fTPM and tpm_ftpm_tee binds at coldplug,
    # but only a runtime that installs optee-ftpm-init gives it a supplicant
    # and an NV store. Without them it is in dictionary-attack lockout every
    # boot: systemd's SRK setup fails, and as Type=oneshot with no timeout it
    # can hold sysinit.target. optee-ftpm-setup.sh writes supplicant.env once
    # the store is up and before it loads the driver; /run crosses the switch
    # to the real root. A file from the optee-ftpm-init package would not do:
    # the documented opt-in installs it in the initramfs only.
    for u in systemd-tpm2-setup-early systemd-tpm2-setup; do
        install -d ${D}${systemd_system_unitdir}/$u.service.d
        cat > ${D}${systemd_system_unitdir}/$u.service.d/50-avocado-jetson-ftpm.conf <<EOF
[Unit]
ConditionPathExists=/run/optee-ftpm/supplicant.env

[Service]
TimeoutSec=30s
EOF
    done
}

FILES:${PN} = "${nonarch_libdir}/systemd/system-preset/89-avocado-jetson.preset \
               ${systemd_system_unitdir}/systemd-tpm2-setup-early.service.d \
               ${systemd_system_unitdir}/systemd-tpm2-setup.service.d"
