#!/bin/sh
# Pre-install script for Tegra A/B rootfs updates
# Determines inactive slot, resolves the target partition on the disk the
# running rootfs lives on, and prepares a stable symlink for SWUpdate's raw
# handler.

set -e

LOGFILE="/tmp/swupdate-tegra-ab.log"
VARS_FILE="/tmp/tegra-ab-vars"
TARGET_SYMLINK="/tmp/target_rootfs"   # set device="/tmp/target_rootfs" in sw-description to use this

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGFILE"
}

# A board can carry APP/APP_b on more than one disk (an SD card and an NVMe,
# each provisioned). The labels name a role, not a disk, so the slot to write
# is the target label on the disk the running rootfs came from: that is the
# disk the initrd booted, and the one the next boot will read.
#
# Prints the sysfs directory of the partition / is mounted from, following a
# device-mapper root down to its single backing partition. Prints nothing
# when / is not on a partition (an overlay or tmpfs root, or a dm device with
# several backing devices). Uses only /proc and /sys, no util-linux.
booted_root_part() {
    majmin=""
    while read -r _ _ mm _ mnt _; do
        if [ "$mnt" = "/" ]; then majmin="$mm"; fi
    done < /proc/self/mountinfo
    [ -n "$majmin" ] || return 0
    dir=$(cd "/sys/dev/block/$majmin" 2>/dev/null && pwd -P) || return 0
    for _ in 1 2 3 4; do
        if [ -f "$dir/partition" ]; then
            echo "$dir"
            return 0
        fi
        set -- "$dir"/slaves/*
        { [ $# -eq 1 ] && [ -e "$1" ]; } || return 0
        dir=$(cd "$1" && pwd -P) || return 0
    done
}

# Prints /dev/<name> for each partition whose GPT name is $1, on the disk $2
# (a /sys/block name), or on every disk when $2 is empty.
parts_labelled() {
    label="$1"
    if [ -n "$2" ]; then
        set -- /sys/block/"$2"/*/partition
    else
        set -- /sys/class/block/*/partition
    fi
    for p in "$@"; do
        [ -f "$p" ] || continue
        d="${p%/partition}"
        while IFS='=' read -r key val; do
            if [ "$key" = "PARTNAME" ] && [ "$val" = "$label" ]; then
                echo "/dev/${d##*/}"
            fi
        done < "$d/uevent"
    done
}

# Prints $1 when it holds exactly one word.
only_one() {
    # shellcheck disable=SC2086 # one device per word
    set -- $1
    if [ $# -eq 1 ]; then echo "$1"; fi
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

# Resolve target device on the disk the running rootfs lives on. When that
# disk cannot be determined, the labels alone are used only if exactly one
# partition carries the target label and exactly one carries the active one.
# A second copy of either means a second install, and picking one is a guess.
ROOT_PART="$(booted_root_part)"
if [ -n "$ROOT_PART" ]; then
    BOOT_DISK="${ROOT_PART%/*}"
    BOOT_DISK="${BOOT_DISK##*/}"
    ACTIVE_DEV="/dev/${ROOT_PART##*/}"
    log "Running rootfs: $ACTIVE_DEV on disk $BOOT_DISK"
    CANDIDATES="$(parts_labelled "$TARGET_PARTLABEL" "$BOOT_DISK")"
    WHERE="on the booted disk $BOOT_DISK"
else
    log "WARNING: cannot tell which disk / is mounted from; resolving $TARGET_PARTLABEL by label"
    CANDIDATES="$(parts_labelled "$TARGET_PARTLABEL" "")"
    ACTIVES="$(parts_labelled "$ACTIVE_PARTLABEL" "")"
    ACTIVE_DEV="$(only_one "$ACTIVES")"
    if [ -z "$ACTIVE_DEV" ]; then
        log "ERROR: need exactly one partition labelled '$ACTIVE_PARTLABEL' when the booted disk is unknown, found: ${ACTIVES:-none}"
        exit 1
    fi
    WHERE="on any disk"
fi
TARGET_DEV="$(only_one "$CANDIDATES")"
if [ -z "$TARGET_DEV" ] || [ ! -b "$TARGET_DEV" ]; then
    log "ERROR: need exactly one partition labelled '$TARGET_PARTLABEL' $WHERE, found: ${CANDIDATES:-none}"
    # Show what's available to aid debugging
    ls -l /dev/disk/by-partlabel/ 2>&1 | tee -a "$LOGFILE" || true
    blkid 2>&1 | tee -a "$LOGFILE" || true
    exit 1
fi

# Extra sanity: ensure active partition is not selected
if [ -n "$ACTIVE_DEV" ] && [ "$ACTIVE_DEV" = "$TARGET_DEV" ]; then
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
} > "$VARS_FILE"

log "Variables written to $VARS_FILE"
log "Pre-install completed successfully"
exit 0
