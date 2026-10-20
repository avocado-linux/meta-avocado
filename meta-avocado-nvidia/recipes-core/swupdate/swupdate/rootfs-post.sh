#!/bin/sh
# Post-install script for Tegra A/B rootfs updates
# Switch the active boot slot to the just-updated (inactive) slot

set -e

LOGFILE="/tmp/swupdate-tegra-ab.log"
VARS_FILE="/tmp/tegra-ab-vars"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGFILE"
}

# Same as rootfs-pre.sh: SWUpdate runs each script on its own, so the
# helpers are carried in both, and test-rootfs-ab-target.sh fails if the
# copies differ.
#
# Prints the sysfs directory of the partition / is mounted from, following a
# device-mapper root down to its single backing partition, or nothing.
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

# Confirm the device is the target label on the disk the running rootfs lives
# on (or, when that disk cannot be determined, the only partition carrying
# the label, with the active label also on exactly one partition) before
# switching the slot. Activating a slot written to another disk would boot
# the old rootfs under a slot the bootloader thinks is new.
ROOT_PART="$(booted_root_part)"
if [ -n "$ROOT_PART" ]; then
    BOOT_DISK="${ROOT_PART%/*}"
    BOOT_DISK="${BOOT_DISK##*/}"
    EXPECTED="$(parts_labelled "$TEGRA_TARGET_PARTLABEL" "$BOOT_DISK")"
    WHERE="on the booted disk $BOOT_DISK"
else
    log "WARNING: cannot tell which disk / is mounted from; checking $TEGRA_TARGET_PARTLABEL by label"
    EXPECTED="$(parts_labelled "$TEGRA_TARGET_PARTLABEL" "")"
    WHERE="on any disk"
    ACTIVES="$(parts_labelled "${TEGRA_ACTIVE_PARTLABEL:-}" "")"
    if [ -z "${TEGRA_ACTIVE_PARTLABEL:-}" ] || [ -z "$(only_one "$ACTIVES")" ]; then
        log "ERROR: need exactly one partition labelled '${TEGRA_ACTIVE_PARTLABEL:-}' when the booted disk is unknown, found: ${ACTIVES:-none}"
        log "       Not switching the boot slot."
        exit 1
    fi
fi
if [ "$EXPECTED" != "$TEGRA_TARGET_DEV" ]; then
    log "ERROR: preinstall wrote $TEGRA_TARGET_DEV, but the partition labelled"
    log "       '$TEGRA_TARGET_PARTLABEL' $WHERE is: ${EXPECTED:-none}"
    log "       Not switching the boot slot."
    exit 1
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
