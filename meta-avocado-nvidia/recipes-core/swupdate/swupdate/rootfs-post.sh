#!/bin/sh
# Post-install script for Tegra A/B rootfs updates
# Switch the active boot slot to the just-updated (inactive) slot

set -e

LOGFILE="/tmp/swupdate-tegra-ab.log"
VARS_FILE="/tmp/tegra-ab-vars"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGFILE"
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

# Confirm the device really corresponds to the intended PARTLABEL
BYLABEL="/dev/disk/by-partlabel/$TEGRA_TARGET_PARTLABEL"
if [ -L "$BYLABEL" ]; then
    RESOLVED="$(readlink -f "$BYLABEL" || true)"
    if [ -n "$RESOLVED" ] && [ "$RESOLVED" != "$TEGRA_TARGET_DEV" ]; then
        log "WARNING: $BYLABEL resolves to $RESOLVED, but preinstall reported $TEGRA_TARGET_DEV"
    fi
fi

# 4) Optional filesystem sanity (skip if blkid not available)
if command -v blkid >/dev/null 2>&1; then
    FS_TYPE="$(blkid -o value -s TYPE "$TEGRA_TARGET_DEV" 2>/dev/null || true)"
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
