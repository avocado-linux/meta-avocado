#!/bin/sh
# Unlock or first-boot-format the /var LUKS2 container.
# Called from cryptsetup-var.service in the initramfs.
#
# Usage: cryptsetup-var.sh <block-device>
#   e.g. cryptsetup-var.sh /dev/mmcblk1p8
#
# The script uses var-key.sh (in the same directory) to derive the key.
# Exit non-zero on any failure so the unit fails rather than silently
# mounting a plaintext /var.
#
# POSIX sh (not bash) so the initramfs needs no bash dependency.
set -eu

VAR_DEV="${1:-}"
MAP_NAME="var"
MAPPER="/dev/mapper/${MAP_NAME}"

[ -z "$VAR_DEV" ] && { echo "Usage: $0 <block-device>" >&2; exit 1; }
[ -b "$VAR_DEV" ] || { echo "Not a block device: $VAR_DEV" >&2; exit 1; }

SCRIPT_DIR="$(dirname "$0")"
KEY_SCRIPT="${SCRIPT_DIR}/var-key.sh"

# Derive the key (never hardcoded; sourced from var-key.sh).
# The key is written to a temp file to avoid exposure in /proc. Use /run, not
# /tmp: systemd mounts a fresh tmpfs over /tmp partway through early boot, which
# would shadow a key file created here before that mount and make cryptsetup's
# --key-file fail with "Failed to open key file". /run is a stable early tmpfs
# (RAM-only, never swapped or remounted) - the right place for transient secrets.
KEY_FILE=$(mktemp -p /run)
trap 'rm -f "$KEY_FILE"' EXIT
"$KEY_SCRIPT" > "$KEY_FILE"

if cryptsetup isLuks "$VAR_DEV" 2>/dev/null; then
    # Existing LUKS2 container - open it.
    echo "cryptsetup-var: opening existing LUKS2 container on $VAR_DEV"

    # Phase-2: Try TPM2-sealed keyslot first (PCR 7).
    TPM2_OPENED=0
    if [ -e /dev/tpm0 ] && command -v systemd-cryptenroll >/dev/null 2>&1; then
        if cryptsetup open --token-only "$VAR_DEV" "$MAP_NAME" 2>/dev/null; then
            echo "cryptsetup-var: opened via TPM2 token"
            TPM2_OPENED=1
            # Retire Argon2id keyslot only after confirmed TPM2 unseal.
            # luksKillSlot is never called without this guard.
            echo "cryptsetup-var: retiring Argon2id keyslot (TPM2 unseal verified)"
            cryptsetup luksKillSlot --key-file "$KEY_FILE" "$VAR_DEV" 0 || true
        fi
    fi

    if [ "$TPM2_OPENED" -eq 0 ]; then
        echo "cryptsetup-var: TPM2 not available or unseal failed - falling back to Argon2id keyslot"
        if ! cryptsetup luksOpen --key-file "$KEY_FILE" "$VAR_DEV" "$MAP_NAME" 2>/dev/null; then
            echo "cryptsetup-var: Argon2id open failed - keyslot may have been retired after TPM2 verification" >&2
            echo "cryptsetup-var: TPM2 unseal required; check PCR 7 state (Secure Boot policy)" >&2
            exit 1
        fi
    fi

    # Resize LUKS container if the partition grew (e.g. after avocado-grow-var).
    PARTITION_SECTORS=$(blockdev --getsz "$VAR_DEV")
    DATA_OFFSET=$(dmsetup table "$MAP_NAME" 2>/dev/null | awk '{print $8}')
    DM_SECTORS=$(blockdev --getsz "$MAPPER")
    EXPECTED_DM=$(( PARTITION_SECTORS - DATA_OFFSET ))
    if [ "$DM_SECTORS" -lt "$EXPECTED_DM" ]; then
        echo "cryptsetup-var: resizing LUKS container to fill partition"
        cryptsetup resize --key-file "$KEY_FILE" "$MAP_NAME"
        btrfs filesystem resize max "$MAPPER"
    fi
else
    # First boot - format the partition as LUKS2 (aes-xts-plain64, 512-bit key).
    echo "cryptsetup-var: first boot - formatting $VAR_DEV as LUKS2"
    cryptsetup luksFormat \
        --type luks2 \
        --cipher aes-xts-plain64 \
        --key-size 512 \
        --hash sha256 \
        --key-file "$KEY_FILE" \
        --batch-mode \
        "$VAR_DEV"
    cryptsetup luksOpen --key-file "$KEY_FILE" "$VAR_DEV" "$MAP_NAME"
    echo "cryptsetup-var: creating BTRFS filesystem inside LUKS container"
    mkfs.btrfs -f "$MAPPER"

    # Phase-2: Enroll TPM2 keyslot sealed to PCR 7 (Secure Boot state).
    # Slot 0 (Argon2id) is retained as the recovery path until task 3.2
    # confirms this slot unseals successfully on the next boot.
    if [ -e /dev/tpm0 ] && command -v systemd-cryptenroll >/dev/null 2>&1; then
        echo "cryptsetup-var: enrolling TPM2 keyslot (PCR 7)"
        systemd-cryptenroll --tpm2-device=auto --tpm2-pcrs=7 "$VAR_DEV"
    fi
fi

echo "cryptsetup-var: $MAPPER ready"
