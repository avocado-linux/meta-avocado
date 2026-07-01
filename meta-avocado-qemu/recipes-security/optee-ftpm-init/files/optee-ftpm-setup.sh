#!/bin/sh
# Bring up the OP-TEE fTPM in the initramfs so /dev/tpm0 exists before
# cryptsetup-var's TPM2 PCR-7 enroll.
#
# The fTPM TA is embedded as an OP-TEE early TA (built into BL32 by meta-arm's
# optee-ftpm/optee-os wiring), but its NV secure storage is REE-FS - qemu has no
# RPMB - and REE-FS is serviced by tee-supplicant in userspace. So:
#   * tpm_ftpm_tee is a module (not built-in): loaded here, after tee-supplicant,
#     rather than probing at kernel init when the supplicant isn't running yet.
#   * the fTPM NV (the seed the SRK derives from) is kept on the recovery
#     partition rather than the initramfs tmpfs, at tee-supplicant's compiled-in
#     path /var/lib/tee.
#
# Reboot-survival caveat: OP-TEE's secure storage anti-rollback needs an RPMB
# hardware counter. Real ARM eMMC has it and the seal reopens every boot; the
# QEMU 'virt' machine has no RPMB, so on qemuarm64 the seal is created on first
# boot but /var falls back to Argon2id on reboot. See optee-ftpm-init.bb.
set -u
# Surface progress on the console (the initrd journal is not forwarded here).
exec >/dev/console 2>&1

TEE_DEV=/dev/disk/by-partlabel/recovery
[ -b "$TEE_DEV" ] || { echo "optee-ftpm: no recovery partition, skipping fTPM bring-up"; exit 0; }

# Mount the persistent TEE store, formatting it (btrfs, already in the initramfs
# for /var) on first boot. tee-supplicant was built with
# TEE_FS_PARENT_PATH=/var/lib/tee, so that exact path must be the persistent
# mount or the fTPM's NV lands on the initramfs tmpfs and is lost on reboot.
TEE_STORE=/var/lib/tee
mkdir -p "$TEE_STORE"
if ! mount "$TEE_DEV" "$TEE_STORE" 2>/dev/null; then
    echo "optee-ftpm: first boot - formatting TEE store on $TEE_DEV"
    # If we cannot format and mount the persistent store, do not fall through:
    # tee-supplicant would keep the fTPM NV on the initramfs tmpfs, silently
    # non-persistent. Skip fTPM bring-up instead so /var takes its Argon2id path.
    if ! mkfs.btrfs -M -f -L teestore "$TEE_DEV" || ! mount "$TEE_DEV" "$TEE_STORE"; then
        echo "optee-ftpm: could not prepare persistent TEE store on $TEE_DEV;" \
             "skipping fTPM bring-up (/var will fall back to Argon2id)" >&2
        exit 0
    fi
fi

# tee-supplicant services the fTPM's REE-FS storage (and the RPC in general).
tee-supplicant -d

# Load the fTPM driver now that storage is available; it opens a session to the
# embedded early TA and registers /dev/tpm0.
modprobe tpm_ftpm_tee || true

# Give the chip time to appear so the enroll finds it.
i=0
while [ ! -e /dev/tpm0 ] && [ "$i" -lt 100 ]; do i=$((i + 1)); sleep 0.1; done
if [ -e /dev/tpm0 ]; then
    echo "optee-ftpm: /dev/tpm0 ready"
else
    echo "optee-ftpm: /dev/tpm0 did not appear - /var will fall back to Argon2id" >&2
fi
