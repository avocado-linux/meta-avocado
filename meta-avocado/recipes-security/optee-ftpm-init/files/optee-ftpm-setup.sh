#!/bin/sh
# Bring up the OP-TEE fTPM in the initramfs so /dev/tpm0 exists before
# cryptsetup-var's TPM2 PCR-7 enroll.
#
# The fTPM TA is embedded as an OP-TEE early TA (built into BL32 by meta-arm's
# optee-ftpm/optee-os wiring), but its NV secure storage is REE-FS on every
# machine that runs this today (see optee-ftpm-init.bb for why, per machine),
# and REE-FS is serviced by tee-supplicant in userspace. So:
#   * tpm_ftpm_tee is a module (not built-in): loaded here, after tee-supplicant,
#     rather than probing at kernel init when the supplicant isn't running yet.
#   * the fTPM NV (the seed the SRK derives from) is kept on the recovery
#     partition rather than the initramfs tmpfs, at tee-supplicant's compiled-in
#     path /var/lib/tee.
#
# Reboot-survival caveat: OP-TEE's secure storage anti-rollback needs an RPMB
# counter, and no machine running this uses one yet - qemuarm64 has no RPMB at
# all, and the i.MX93 OP-TEE has the hardware but is not built with
# CFG_RPMB_FS=y. So the seal is created on first boot and /var falls back to
# Argon2id on reboot. See optee-ftpm-init.bb.
set -u
# Surface progress on the console (the initrd journal is not forwarded here).
exec >/dev/console 2>&1

# Fail-closed pre-flight: refuse before any privileged action (mount, mkfs,
# tee-supplicant, modprobe) if either (a) this device's base image never
# declared ftpm, or (b) the kernel cannot actually deliver OP-TEE. These two
# refusal paths must stay distinguishable per design.md A6 - a declaration
# problem and a kernel problem need different fixes, so collapsing them into
# one message would hide which side to fix. Mirrors cryptsetup-var.sh's
# check_capability_declared/check_dmcrypt_available shape.
CAPABILITIES_FILE="/etc/avocado-security-capabilities"
REQUIRED_CAPABILITY="ftpm"

check_capability_declared() {
    if [ ! -f "$CAPABILITIES_FILE" ]; then
        echo "optee-ftpm: $CAPABILITIES_FILE is absent - this device's base image never declared $REQUIRED_CAPABILITY" >&2
        exit 1
    fi
    declared="$(cat "$CAPABILITIES_FILE")"
    for token in $declared; do
        [ "$token" = "$REQUIRED_CAPABILITY" ] && return 0
    done
    echo "optee-ftpm: $REQUIRED_CAPABILITY is missing from this device's AVOCADO_SECURITY_CAPABILITIES declaration (declares: ${declared:-<empty>})" >&2
    exit 1
}

check_optee_available() {
    [ -e /sys/bus/tee ] && return 0
    echo "optee-ftpm: this device's kernel cannot deliver OP-TEE - fTPM is unavailable" >&2
    exit 1
}

check_capability_declared
check_optee_available

TEE_DEV=/dev/disk/by-partlabel/recovery
[ -b "$TEE_DEV" ] || { echo "optee-ftpm: no recovery partition, skipping fTPM bring-up"; exit 0; }

# Mount the persistent TEE store, formatting it (btrfs, already in the initramfs
# for /var) on first boot. tee-supplicant was built with
# TEE_FS_PARENT_PATH=/var/lib/tee, so that exact path must be the persistent
# mount or the fTPM's NV lands on the initramfs tmpfs and is lost on reboot.
TEE_STORE=/var/lib/tee
mkdir -p "$TEE_STORE"
if ! mount "$TEE_DEV" "$TEE_STORE" 2>/dev/null; then
    # Probe before formatting, same convention as cryptsetup-var.sh's
    # ensure_fs: mount can fail for reasons other than "no filesystem yet"
    # (a dirty btrfs needing recovery, a foreign signature), and -f would
    # clobber the recovery partition's real contents in exactly that case.
    if blkid -p "$TEE_DEV" >/dev/null 2>&1; then
        echo "optee-ftpm: $TEE_DEV has a filesystem but would not mount;" \
             "skipping fTPM bring-up (/var will fall back to Argon2id)" >&2
        exit 0
    fi
    echo "optee-ftpm: first boot - formatting TEE store on $TEE_DEV"
    # If we cannot format and mount the persistent store, do not fall through:
    # tee-supplicant would keep the fTPM NV on the initramfs tmpfs, silently
    # non-persistent. Skip fTPM bring-up instead so /var takes its Argon2id path.
    if ! mkfs.btrfs -M -L teestore "$TEE_DEV" || ! mount "$TEE_DEV" "$TEE_STORE"; then
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

# Give the chip time to appear so the enroll finds it. Whole-second sleep,
# not fractional: busybox's sleep applet needs FEATURE_FANCY_SLEEP to accept
# a fractional argument, and this minimal initramfs's busybox is not
# guaranteed to have it - an unsupported "0.1" errors out instantly, the
# loop spins its iterations with no real wait, and the chip is reported
# missing on a board where it would have appeared. cryptsetup-var.sh's own
# TPM wait uses whole seconds for the same reason.
i=0
while [ ! -e /dev/tpm0 ] && [ "$i" -lt 10 ]; do i=$((i + 1)); sleep 1; done
if [ -e /dev/tpm0 ]; then
    echo "optee-ftpm: /dev/tpm0 ready"
else
    echo "optee-ftpm: /dev/tpm0 did not appear - /var will fall back to Argon2id" >&2
fi
