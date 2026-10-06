#!/bin/sh
# Pre-install script for Tegra A/B rootfs updates
# Determines the inactive slot, resolves its partition on the disk this system
# booted from, and prepares a stable symlink for SWUpdate's raw handler.

set -e

LOGFILE="/tmp/swupdate-tegra-ab.log"
VARS_FILE="/tmp/tegra-ab-vars"
TARGET_SYMLINK="/tmp/target_rootfs" # set device="/tmp/target_rootfs" in sw-description to use this

# Diagnostics go to stderr, not stdout. resolve_partlabel_on_disk() returns its
# result by echoing it and is called inside "$(...)", so anything log() writes to
# stdout is captured as that result instead of being printed. That is not
# hypothetical: with log() on stdout, the "more than one partition carries this
# label" refusal did not refuse. The caller tests the captured value for
# emptiness, a log line is not empty, so the script took the message itself as a
# device path, symlinked it, and reported success - defeating the one guard
# standing between an ambiguous layout and writing the payload somewhere nobody
# chose.
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGFILE" >&2
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

# GPT partition name for one partition, read from the kernel.
#
# blkid cannot answer this here. This script runs in the booted rootfs, which
# ships busybox's blkid, and that reports TYPE/UUID/LABEL only - no PARTLABEL -
# while silently ignoring -t, -o and -s. It does not fail when asked for a field
# it does not implement; it answers a different question. Measured on a Jetson
# Orin Nano: `blkid -o value -s PARTLABEL /dev/nvme0n1p1` prints
# `/dev/nvme0n1p1: TYPE="erofs"`, which is not empty, so testing for emptiness to
# mean "unavailable" yields a confident wrong answer rather than a blank.
#
# The kernel publishes the same GPT name as PARTNAME in each partition's uevent,
# needing no package at all. avocado-tegra-init reads partitions this way in
# find_datapart_on_disk().
partname_of() {
  [ -f "$1/uevent" ] || return 1
  while IFS='=' read -r key val; do
    if [ "$key" = "PARTNAME" ]; then
      # printf, not echo: a name starting with -n or -e, or containing a
      # backslash, is an option or an escape to some echo implementations.
      printf '%s\n' "$val"
      return 0
    fi
  done <"$1/uevent"
  return 1
}

resolve_partlabel_on_disk() {
  # A PARTLABEL names a role, not a disk. A board provisioned to more than one
  # medium carries APP and APP_b on each of them, so resolving a label across
  # the whole system can return a partition on a disk this system did not boot
  # from - SWUpdate would write the payload there while nvbootctrl flips the
  # slot on the disk that never received it, and the board reboots into a
  # stale rootfs. Restrict the search to the disk we are running from, and
  # refuse rather than choose when it is still not unique.
  #
  # Walking that disk's own partition directories is what restricts it. The
  # previous form searched every disk and filtered by name prefix, which had to
  # anchor carefully so that /dev/nvme0n11p2 did not pass for /dev/nvme0n1;
  # nvme0n11 is a sibling of nvme0n1 in /sys/block rather than a child, so
  # enumerating one disk's children cannot express that mistake.
  label="$1"
  disk="$2"
  diskname="${disk#/dev/}"
  found=""
  count=0

  # An absent disk directory is not "no partition carries the label" - it means
  # the name we derived does not exist in sysfs at all. Saying so beats letting
  # an unmatched glob report the same thing as a genuine miss.
  if [ ! -d "/sys/block/$diskname" ]; then
    log "ERROR: no sysfs directory for $disk (/sys/block/$diskname)"
    return 1
  fi

  for partdir in "/sys/block/$diskname/$diskname"*; do
    [ "$(partname_of "$partdir" || true)" = "$label" ] || continue
    cand="/dev/$(basename "$partdir")"
    # A matching partition with no device node is worth a line: it is the one
    # case where the label was found and the result still comes back empty.
    if [ ! -b "$cand" ]; then
      log "WARNING: $partdir carries PARTLABEL='$label' but $cand is not a block device"
      continue
    fi
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
# Both halves of this path are already known, so there is nothing to search for:
# /dev/nvme0n1 plus /dev/nvme0n1p1 gives /sys/block/nvme0n1/nvme0n1p1.
RUNNING_LABEL="$(partname_of "/sys/block/${BOOT_DISK#/dev/}/${ACTIVE_DEV#/dev/}" || true)"
if [ -z "$RUNNING_LABEL" ]; then
  # Previously an unreadable label was skipped, on the reading that it should
  # not block an update. Reading the kernel's own PARTNAME changes what a blank
  # means: every GPT partition has one, and nothing else in this script works
  # without GPT names, so a blank says the partition we booted is not the shape
  # the rest of this assumes. Refuse before reaching the part that writes.
  log "ERROR: no PARTNAME in sysfs for $ACTIVE_DEV - not a GPT partition?"
  exit 1
fi
if [ "$RUNNING_LABEL" != "$ACTIVE_PARTLABEL" ]; then
  log "ERROR: nvbootctrl reports slot $CURRENT_SLOT (active label"
  log "       '$ACTIVE_PARTLABEL') but / is '$RUNNING_LABEL' on $ACTIVE_DEV"
  exit 1
fi

# Resolve target device, on the booted disk only
TARGET_DEV="$(resolve_partlabel_on_disk "$TARGET_PARTLABEL" "$BOOT_DISK" || true)"
if [ -z "$TARGET_DEV" ]; then
  log "ERROR: Could not resolve PARTLABEL='$TARGET_PARTLABEL' on $BOOT_DISK"
  # Dump the names the resolver matches on, using its own glob so this shows the
  # candidate set it actually considered. A blkid dump said nothing useful here:
  # on this rootfs it cannot report PARTNAME at all.
  boot_diskname="${BOOT_DISK#/dev/}"
  log "  partitions on $BOOT_DISK:"
  for partdir in "/sys/block/$boot_diskname/$boot_diskname"*; do
    [ -f "$partdir/uevent" ] || continue
    log "    $(basename "$partdir") PARTNAME=$(partname_of "$partdir" || echo '<none>')"
  done
  # Then say whether the label exists at all. Restricting the search to the boot
  # disk is the point of this change, so the interesting failure is the label
  # sitting on a disk we deliberately did not search - which the first dump, by
  # construction, cannot show.
  log "  same label elsewhere:"
  for diskdir in /sys/block/*; do
    [ "$(basename "$diskdir")" = "$boot_diskname" ] && continue
    for partdir in "$diskdir/$(basename "$diskdir")"*; do
      [ -f "$partdir/uevent" ] || continue
      [ "$(partname_of "$partdir" || true)" = "$TARGET_PARTLABEL" ] || continue
      log "    $(basename "$partdir") on $(basename "$diskdir")"
    done
  done
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
