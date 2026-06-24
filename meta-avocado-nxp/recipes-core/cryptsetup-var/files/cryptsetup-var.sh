#!/bin/bash
# Unlock or first-boot-format the /var LUKS2 container.
# Called from cryptsetup-var.service in the initramfs.
#
# Usage: cryptsetup-var.sh <block-device>
#   e.g. cryptsetup-var.sh /dev/mmcblk1p8
#
# The script uses var-key.sh (in the same directory) to derive the key.
# Exit non-zero on any failure so the unit fails rather than silently
# mounting a plaintext /var.
set -euo pipefail

VAR_DEV="${1:-}"
MAP_NAME="var"
MAPPER="/dev/mapper/${MAP_NAME}"

[ -z "$VAR_DEV" ] && { echo "Usage: $0 <block-device>" >&2; exit 1; }
[ -b "$VAR_DEV" ] || { echo "Not a block device: $VAR_DEV" >&2; exit 1; }

SCRIPT_DIR="$(dirname "$0")"
KEY_SCRIPT="${SCRIPT_DIR}/var-key.sh"

# Derive the key (never hardcoded; sourced from var-key.sh).
# The key is written to a file descriptor to avoid exposure in /proc.
KEY_FILE=$(mktemp)
trap 'rm -f "$KEY_FILE"' EXIT
"$KEY_SCRIPT" > "$KEY_FILE"

if cryptsetup isLuks "$VAR_DEV" 2>/dev/null; then
    # Existing LUKS2 container — open it.
    echo "cryptsetup-var: opening existing LUKS2 container on $VAR_DEV"
    cryptsetup luksOpen --key-file "$KEY_FILE" "$VAR_DEV" "$MAP_NAME"

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
    # First boot — format the partition as LUKS2 (aes-xts-plain64, 512-bit key).
    echo "cryptsetup-var: first boot — formatting $VAR_DEV as LUKS2"
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
fi

echo "cryptsetup-var: $MAPPER ready"
