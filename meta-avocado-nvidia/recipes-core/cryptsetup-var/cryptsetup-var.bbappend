# Jetson /var LUKS key provider (files/var-key.sh). `tegra` is the
# MACHINEOVERRIDE every meta-tegra machine carries, so this covers every
# Avocado Jetson (devkit or carrier) with one override.
FILESEXTRAPATHS:prepend:tegra := "${THISDIR}/files:"

# The TPM2 keyslot is sealed to the OP-TEE fTPM, which the kernel exposes on
# Jetson without any userspace supplicant (tpm_ftpm_tee binds to the UEFI
# `firmware:ftpm` device from the initramfs). What it does need is
# tpm2-tools: the fTPM keeps no NV state across boots and comes up in
# dictionary-attack lockout, which cryptsetup-var.sh resets each boot before
# the token unlock (see ensure_tpm2_unlocked). Verified on an Orin Nano devkit.
RDEPENDS:${PN}:append:tegra = " tpm2-tools"
