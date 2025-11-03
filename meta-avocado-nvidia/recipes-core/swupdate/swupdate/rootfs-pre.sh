#!/bin/sh
# Pre-install script for Tegra A/B rootfs updates
# Determines inactive slot, resolves target partition by PARTLABEL,
# and prepares a stable symlink for SWUpdate's raw handler.

set -e

LOGFILE="/tmp/swupdate-tegra-ab.log"
VARS_FILE="/tmp/tegra-ab-vars"
TARGET_SYMLINK="/tmp/target_rootfs"   # set device="/tmp/target_rootfs" in sw-description to use this

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGFILE"
}

resolve_partlabel() {
    # Resolves /dev/disk/by-partlabel/<LABEL> to the real block device (e.g. /dev/nvme0n1p2)
    # Falls back to blkid if needed.
    label="$1"
    bylabel="/dev/disk/by-partlabel/$label"

    if [ -L "$bylabel" ]; then
        real="$(readlink -f "$bylabel" || true)"
        if [ -n "$real" ] && [ -b "$real" ]; then
            echo "$real"
            return 0
        fi
    fi

    # Fallback via blkid
    real="$(blkid -l -t "PARTLABEL=$label" -o device 2>/dev/null | head -n1 || true)"
    if [ -n "$real" ] && [ -b "$real" ]; then
        echo "$real"
        return 0
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

# Resolve target device
TARGET_DEV="$(resolve_partlabel "$TARGET_PARTLABEL" || true)"
if [ -z "$TARGET_DEV" ]; then
    log "ERROR: Could not resolve device for PARTLABEL='$TARGET_PARTLABEL'"
    # Show what's available to aid debugging
    ls -l /dev/disk/by-partlabel/ 2>&1 | tee -a "$LOGFILE" || true
    blkid 2>&1 | tee -a "$LOGFILE" || true
    exit 1
fi

# Extra sanity: ensure active partition is not selected
ACTIVE_DEV="$(resolve_partlabel "$ACTIVE_PARTLABEL" || true)"
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
