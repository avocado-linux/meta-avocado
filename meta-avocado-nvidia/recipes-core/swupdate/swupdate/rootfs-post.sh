#!/bin/sh
# Post-install script for Tegra A/B rootfs updates
# Switch the active boot slot to the just-updated (inactive) slot

set -e

LOGFILE="/tmp/swupdate-tegra-ab.log"
VARS_FILE="/tmp/tegra-ab-vars"

# The functions below are copied verbatim from rootfs-pre.sh, which explains
# each of them. SWUpdate runs each script on its own, so they cannot be shared
# by sourcing, and test-rootfs-ab-target.sh fails if the copies drift apart.
#
# log() writes to stderr for the reason given there: resolve_partlabel_on_disk()
# returns its answer on stdout, and a log line captured as that answer would
# read as a device path.
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGFILE" >&2
}

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

disk_of() {
  case "$1" in
    /dev/nvme* | /dev/mmcblk*) echo "${1%p*}" ;;
    /dev/sd*) echo "${1%%[0-9]*}" ;;
    *) return 1 ;;
  esac
}

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

log "=== Tegra A/B Post-install Script ==="

# 1) Load variables saved by preinstall
if [ -f "$VARS_FILE" ]; then
  # shellcheck disable=SC1090
  . "$VARS_FILE"
else
  log "ERROR: Variables file not found: $VARS_FILE"
  exit 1
fi

: "${TEGRA_INACTIVE_SLOT:?Missing TEGRA_INACTIVE_SLOT}"
: "${TEGRA_TARGET_DEV:?Missing TEGRA_TARGET_DEV}"
: "${TEGRA_TARGET_PARTLABEL:?Missing TEGRA_TARGET_PARTLABEL}"

log "Inactive slot (to activate): $TEGRA_INACTIVE_SLOT"
log "Target device: $TEGRA_TARGET_DEV"
log "Target partlabel: $TEGRA_TARGET_PARTLABEL"

# 2) Basic environment sanity
if ! command -v nvbootctrl >/dev/null 2>&1; then
  log "ERROR: nvbootctrl not found"
  exit 1
fi

# Let udev finish any node updates
if command -v udevadm >/dev/null 2>&1; then
  udevadm settle || true
fi

# 3) Verify target device exists
if [ ! -b "$TEGRA_TARGET_DEV" ]; then
  log "ERROR: Not a block device: $TEGRA_TARGET_DEV"
  exit 1
fi

# Confirm the device is the target label on the disk the running rootfs came
# from, resolved the same way the pre-install resolved it, before switching the
# slot. Activating a slot whose payload went to another disk boots the old
# rootfs under a slot the bootloader believes is new. This replaces a
# /dev/disk/by-partlabel comparison that only warned: with APP_b on two disks
# udev keeps one link per label, so it named whichever disk udev saw last and
# warned on a correct update as readily as on a wrong one.
ACTIVE_DEV="$(active_rootfs_dev || true)"
BOOT_DISK="$(disk_of "$ACTIVE_DEV" || true)"
if [ -z "$BOOT_DISK" ]; then
  log "ERROR: Could not derive the booted disk from '$ACTIVE_DEV'"
  log "       Not switching the boot slot."
  exit 1
fi
EXPECTED="$(resolve_partlabel_on_disk "$TEGRA_TARGET_PARTLABEL" "$BOOT_DISK" || true)"
if [ "$EXPECTED" != "$TEGRA_TARGET_DEV" ]; then
  log "ERROR: preinstall wrote $TEGRA_TARGET_DEV, but PARTLABEL='$TEGRA_TARGET_PARTLABEL'"
  log "       on the booted disk $BOOT_DISK is: ${EXPECTED:-none}"
  log "       Not switching the boot slot."
  exit 1
fi

# 4) Optional filesystem sanity
#
# `command -v blkid` succeeds on this rootfs and tells you nothing useful: the
# blkid there is busybox's, which ignores -o and -s and prints its own line
# instead. `blkid -o value -s TYPE /dev/nvme0n1p2` returns
# `/dev/nvme0n1p2: TYPE="squashfs"` rather than `squashfs`, so the equality test
# below failed on a perfectly good image and warned on every successful update -
# training whoever reads these logs to ignore the one warning that would flag a
# genuinely wrong payload.
#
# Parse the value out of whichever form came back rather than trusting the
# flags. util-linux prints the bare value and passes through the case unchanged.
if command -v blkid >/dev/null 2>&1; then
  FS_TYPE="$(blkid -o value -s TYPE "$TEGRA_TARGET_DEV" 2>/dev/null || true)"
  case "$FS_TYPE" in
    *TYPE=\"*) FS_TYPE="$(printf '%s\n' "$FS_TYPE" | sed -n 's/.*TYPE="\([^"]*\)".*/\1/p')" ;;
  esac
  if [ -n "$FS_TYPE" ]; then
    log "blkid reports filesystem type: $FS_TYPE"
    if [ "$FS_TYPE" != "squashfs" ]; then
      log "WARNING: Expected 'squashfs' but got '$FS_TYPE' — continuing."
    fi
  else
    log "NOTE: blkid did not report a filesystem type; continuing."
  fi
else
  log "NOTE: blkid not available; skipping filesystem check."
fi

# 5) Flush writes just in case
sync

# 6) Switch active boot slot to the updated one
log "Setting active boot slot to $TEGRA_INACTIVE_SLOT"
if nvbootctrl -t rootfs set-active-boot-slot "$TEGRA_INACTIVE_SLOT"; then
  log "Successfully set active boot slot to $TEGRA_INACTIVE_SLOT"
else
  log "ERROR: nvbootctrl failed to set active boot slot"
  exit 1
fi

# 7) Read back current slot (may still show current-running slot until reboot)
NEW_ACTIVE="$(nvbootctrl -t rootfs get-current-slot 2>/dev/null || echo "unknown")"
log "nvbootctrl get-current-slot reports: $NEW_ACTIVE (will take effect on next reboot)"

log "Post-install completed successfully; next boot should use slot $TEGRA_INACTIVE_SLOT"

# 8) Cleanup (keep the log, drop the temp vars)
rm -f "$VARS_FILE" || true

exit 0
