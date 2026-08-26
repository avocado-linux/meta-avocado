# Security *capability* for a vendor kernel: dm-crypt (+ LUKS ciphers,
# TRUSTED_KEYS) and dm-verity, built in unconditionally.
#
# `require` this from a vendor kernel bbappend. It is deliberately NOT gated
# on the encrypted-var / secureboot DISTRO_FEATURES the way the shared
# linux-yocto_%.bbappend is: capability is inert when unused (a few KB of
# text), and a machine whose feed ships one kernel cannot offer "encrypt
# /var" as a per-runtime opt-in (avocado.yaml var.encrypt) unless that one
# kernel can already do it. Policy - whether a device actually encrypts -
# stays with the runtime, never with the kernel build.
#
# Fragments are idempotent overrides, so the same set is correct for a kernel
# whose defconfig already has some of these =y (L4T linux-noble) and for one
# that has them =m or unset (linux-yocto). Verify with
# `bitbake <kernel> -c kernel_configcheck`.
#
# Known ceiling on linux-yocto: its `standard` ktype pins BLK_DEV_DM and
# DM_CRYPT with `# OVERRIDE:$MODULE_OR_Y` (kernel-meta/ktypes/standard/
# standard.cfg), a kern-tools hard override that resolves to =m whenever
# modules are enabled and wins over any later plain fragment - so dm-crypt.cfg's
# =y does NOT take there (measured: DM_CRYPT=m, TRUSTED_KEYS=y, XTS=y). The
# initrd unlock path therefore needs kernel-module-dm-mod / -dm-crypt in the
# initramfs modules packagegroup on such kernels; cryptsetup-var.sh already
# modprobes dm-crypt before it touches the device. The nvidia bbappends do this
# for both Jetson kernels.
FILESEXTRAPATHS:prepend := "${AVOCADO_KERNEL_CFG_DIR}:"
SRC_URI += " file://dm-crypt.cfg file://dm-verity.cfg"
