#!/bin/sh
# Pre-install script for Tegra A/B rootfs updates
# Determines the inactive slot, resolves its partition on the disk this system
# booted from, and prepares a stable symlink for SWUpdate's raw handler.

set -e

LOGFILE="/tmp/swupdate-tegra-ab.log"
VARS_FILE="/tmp/tegra-ab-vars"
TARGET_SYMLINK="/tmp/target_rootfs" # set device="/tmp/target_rootfs" in sw-description to use this

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGFILE"
}

# Device the running rootfs came from. This is the ground truth for which disk
# the A/B pair lives on - nvbootctrl reports a slot number, not a disk.
active_rootfs_dev() {
  if command -v findmnt >/dev/null 2>&1; then
    real="$(findmnt -n -o SOURCE / 2>/dev/null || true)"
    if [ -n "$real" ]; then
      echo "$real"
      return 0
    fi
  fi
  awk '$2 == "/" { print $1; exit }' /proc/mounts
}

# Whole-disk node for a partition node, e.g. /dev/nvme0n1p2 -> /dev/nvme0n1.
disk_of() {
  case "$1" in
    /dev/nvme* | /dev/mmcblk*) echo "${1%p*}" ;;
    /dev/sd*) echo "${1%%[0-9]*}" ;;
    *) return 1 ;;
  esac
}

resolve_partlabel_on_disk() {
  # A PARTLABEL names a role, not a disk. A board provisioned to more than one
  # medium carries APP and APP_b on each of them, so resolving a label across
  # the whole system can return a partition on a disk this system did not boot
  # from - SWUpdate would write the payload there while nvbootctrl flips the
  # slot on the disk that never received it, and the board reboots into a
  # stale rootfs. Restrict the search to the disk we are running from, and
  # refuse rather than choose when it is still not unique.
  label="$1"
  disk="$2"
  found=""
  count=0

  # Anchor on the exact partition prefix rather than accepting either form.
  # Testing both would let /dev/nvme0n11p2 pass for disk /dev/nvme0n1, since
  # the bare "$disk"[0-9]* alternative matches the next namespace's digit.
  case "$disk" in
    /dev/nvme* | /dev/mmcblk*) partprefix="${disk}p" ;;
    *) partprefix="$disk" ;;
  esac

  for cand in $(blkid -t "PARTLABEL=$label" -o device 2>/dev/null || true); do
    case "$cand" in
      "$partprefix"[0-9]*) ;;
      *) continue ;;
    esac
    [ -b "$cand" ] || continue
    found="$cand"
    count=$((count + 1))
  done

  if [ "$count" -eq 1 ]; then
    echo "$found"
    return 0
  fi
  if [ "$count" -gt 1 ]; then
    log "ERROR: $count partitions on $disk carry PARTLABEL='$label'"
  fi
  return 1
}

is_mounted() {
  dev="$1"
  # Prefer findmnt if available, else grep /proc/mounts
  if command -v findmnt >/dev/null 2>&1; then
    if findmnt -n -S "$dev" >/dev/null 2>&1; then
      return 0
    fi
    # Some systems mount via different node; compare by major:minor
    majmin="$(stat -c '%t:%T' "$dev" 2>/dev/null || true)"
    if [ -n "$majmin" ] && findmnt -nr -o SOURCE | xargs -r stat -c '%n %t:%T' 2>/dev/null | awk '{print $2}' | grep -q "^$majmin$"; then
      return 0
    fi
    return 1
  else
    grep -q -w "$dev" /proc/mounts
  fi
}

log "=== Tegra A/B Pre-install Script ==="

# Ensure nvbootctrl exists
if ! command -v nvbootctrl >/dev/null 2>&1; then
  log "ERROR: nvbootctrl not found"
  exit 1
fi

# Let udev settle so by-partlabel links are present
if command -v udevadm >/dev/null 2>&1; then
  udevadm settle || true
fi

# Current slot (0 or 1)
CURRENT_SLOT="$(nvbootctrl -t rootfs get-current-slot 2>/dev/null | tr -d '[:space:]')"
if [ -z "$CURRENT_SLOT" ]; then
  log "ERROR: Unable to determine current slot via nvbootctrl"
  exit 1
fi
log "Current slot: $CURRENT_SLOT"

# Map to inactive and labels
case "$CURRENT_SLOT" in
  0)
    INACTIVE_SLOT=1
    TARGET_PARTLABEL="APP_b"
    ACTIVE_PARTLABEL="APP"
    ;;
  1)
    INACTIVE_SLOT=0
    TARGET_PARTLABEL="APP"
    ACTIVE_PARTLABEL="APP_b"
    ;;
  *)
    log "ERROR: Unexpected current slot value: '$CURRENT_SLOT'"
    exit 1
    ;;
esac

log "Inactive slot: $INACTIVE_SLOT"
log "Target partition label: $TARGET_PARTLABEL"

# The partition we booted from IS the active slot, so take it directly rather
# than looking the active label up and hoping it agrees.
ACTIVE_DEV="$(active_rootfs_dev || true)"
if [ -z "$ACTIVE_DEV" ] || [ ! -b "$ACTIVE_DEV" ]; then
  log "ERROR: Could not determine the block device backing /"
  cat /proc/mounts 2>&1 | tee -a "$LOGFILE" || true
  exit 1
fi

BOOT_DISK="$(disk_of "$ACTIVE_DEV" || true)"
if [ -z "$BOOT_DISK" ]; then
  log "ERROR: Could not derive a whole-disk node from '$ACTIVE_DEV'"
  exit 1
fi
log "Booted rootfs: $ACTIVE_DEV on $BOOT_DISK"

# Cross-check nvbootctrl against the disk. If the slot it reports does not match
# the partition we are actually running, writing the "inactive" slot would
# overwrite something other than what we think, so stop.
RUNNING_LABEL="$(blkid -o value -s PARTLABEL "$ACTIVE_DEV" 2>/dev/null || true)"
if [ -n "$RUNNING_LABEL" ] && [ "$RUNNING_LABEL" != "$ACTIVE_PARTLABEL" ]; then
  log "ERROR: nvbootctrl reports slot $CURRENT_SLOT (active label"
  log "       '$ACTIVE_PARTLABEL') but / is '$RUNNING_LABEL' on $ACTIVE_DEV"
  exit 1
fi

# Resolve target device, on the booted disk only
TARGET_DEV="$(resolve_partlabel_on_disk "$TARGET_PARTLABEL" "$BOOT_DISK" || true)"
if [ -z "$TARGET_DEV" ]; then
  log "ERROR: Could not resolve PARTLABEL='$TARGET_PARTLABEL' on $BOOT_DISK"
  # Show what's available to aid debugging
  blkid 2>&1 | tee -a "$LOGFILE" || true
  exit 1
fi

if [ "$ACTIVE_DEV" = "$TARGET_DEV" ]; then
  log "ERROR: Resolved target device matches active device ($ACTIVE_DEV)"
  exit 1
fi

# Ensure target is not mounted
if is_mounted "$TARGET_DEV"; then
  log "ERROR: Target device '$TARGET_DEV' appears to be mounted"
  findmnt -n -S "$TARGET_DEV" 2>/dev/null || true
  grep -w "$TARGET_DEV" /proc/mounts 2>/dev/null || true
  exit 1
fi

# Optional: basic size sanity (only if squashfs present in the .swu staging path)
# Skipped here because the preinstall does not know payload path reliably.

log "Target device resolved: $TARGET_DEV"

# Prepare a stable symlink for sw-description's device="/tmp/target_rootfs"
# (symlink to block dev works; raw handler opens the resolved path)
if [ -L "$TARGET_SYMLINK" ] || [ -e "$TARGET_SYMLINK" ]; then
  rm -f "$TARGET_SYMLINK"
fi
ln -s "$TARGET_DEV" "$TARGET_SYMLINK"
log "Created symlink: $TARGET_SYMLINK -> $TARGET_DEV"

# Export handy vars for postinstall / debugging
{
  echo "TEGRA_INACTIVE_SLOT=$INACTIVE_SLOT"
  echo "TEGRA_TARGET_DEV=$TARGET_DEV"
  echo "TEGRA_TARGET_PARTLABEL=$TARGET_PARTLABEL"
  echo "TEGRA_ACTIVE_PARTLABEL=$ACTIVE_PARTLABEL"
  echo "TEGRA_TARGET_SYMLINK=$TARGET_SYMLINK"
} >"$VARS_FILE"

log "Variables written to $VARS_FILE"
log "Pre-install completed successfully"
exit 0
