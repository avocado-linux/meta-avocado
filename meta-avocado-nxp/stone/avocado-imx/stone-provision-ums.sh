#!/usr/bin/env bash
#
# ums profile for i.MX93: write the fwup archive to the eMMC (or card) that
# U-Boot exports as a USB mass-storage disk.
#
# Hardware prep: at the U-Boot prompt run `ums 0 mmc <dev>` (eMMC is usually
# mmc 0). The exported disk appears on the host as a block device; the operator
# names it in AVOCADO_PROVISION_DEVICE. No disk is searched for here: a search
# could pick the wrong one, and the profile is told the target, never guesses.
#
# Environment:
#   AVOCADO_PROVISION_DEVICE     required: the exported whole disk
#   AVOCADO_PROVISION_FORCE      see avocado_safe_disk_confirm
#   AVOCADO_PROVISION_DRY_RUN=1  run every guard and print the writes instead
#   AVOCADO_PROVISION_FWUP_TASK  complete only; upgrade is refused

set -e
set -u
set -o pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=/dev/null # sibling file, absent from a standalone lint
. "${SCRIPT_DIR}/avocado-safe-disk.sh"

# Run-mode variables are validated before any guard or write.
avocado_safe_disk_modes ums 1 0 || exit 1

# Refuse first: with no named device nothing below has a target.
if [ -z "${AVOCADO_PROVISION_DEVICE:-}" ]; then
  echo "ERROR: AVOCADO_PROVISION_DEVICE is required: the disk U-Boot exports with \`ums 0 mmc <dev>\`." >&2
  exit 1
fi

archive_name=$(jq -r .storage_devices.rootdisk.out "$AVOCADO_STONE_MANIFEST")
if [ -z "$archive_name" ] || [ "$archive_name" = "null" ]; then
  echo "ERROR: could not extract archive name from manifest" >&2
  exit 1
fi
archive_file="${AVOCADO_STONE_BUILD_DIR}/${archive_name}"
if [ ! -f "$archive_file" ]; then
  echo "ERROR: archive file not found: $archive_file" >&2
  exit 1
fi

# The named path only says what the operator typed. Nothing is shown or written
# until it is a whole USB or MMC disk that does not hold the running root.
avocado_safe_disk_check_device "$AVOCADO_PROVISION_DEVICE" || exit 1
DEV=$AVOCADO_SAFE_DISK_DEV

avocado_safe_disk_confirm "$DEV" || exit 1

# A desktop may auto-mount the exported partitions. Release what is mounted
# here, then refuse whatever is still mounted or in use.
for part in $(mount | awk -v d="$DEV" '$1 == d || (index($1, d) == 1 && substr($1, length(d) + 1) ~ /^p?[0-9]+$/) { print $1 }' | sort -u); do
  echo "Unmounting ${part}..."
  avocado_safe_disk_write umount "$part" || {
    echo "ERROR: failed to unmount ${part}" >&2
    exit 1
  }
done
avocado_safe_disk_unmounted "$DEV" || exit 1

fwup_task=$(avocado_safe_disk_fwup_task) || exit 1
echo "=== Writing ${archive_name} to ${DEV} ==="
avocado_safe_disk_write fwup -a -u -i "$archive_file" -d "$DEV" -t "$fwup_task" || {
  echo "ERROR: fwup failed to write system image" >&2
  exit 1
}

if [ "${AVOCADO_PROVISION_DRY_RUN:-}" = "1" ]; then
  avocado_safe_disk_finish "$DEV"
  exit 0
fi
sync

cat <<'EOT'

Provisioning complete. If you ran `ums` yourself at the U-Boot prompt (Door A),
release the export there now (Ctrl-C) before resetting the board.
EOT
