#!/bin/sh
# Post-install for Tegra A/B kernel+dtb updates (cboot slots)
set -e

LOGFILE="/tmp/swupdate-tegra-ab.log"
VARS_FILE="/tmp/tegra-ab-kernel.vars"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [kernel-post] $*" | tee -a "$LOGFILE"; }

log "=== Kernel/DTB Post-install ==="

# Load vars from preinstall
[ -f "$VARS_FILE" ] || { log "ERROR: Vars file not found: $VARS_FILE"; exit 1; }
# shellcheck disable=SC1090
. "$VARS_FILE"

: "${K_INACTIVE_SLOT:?Missing K_INACTIVE_SLOT}"
: "${K_TARGET_DEV:?Missing K_TARGET_DEV}"
: "${K_TARGET_DTB_DEV:?Missing K_TARGET_DTB_DEV}"

command -v nvbootctrl >/dev/null 2>&1 || { log "ERROR: nvbootctrl not found"; exit 1; }
command -v udevadm >/dev/null 2>&1 && udevadm settle || true

# Basic exist checks (no mount checks needed for kernel/dtb)
[ -b "$K_TARGET_DEV" ]      || { log "ERROR: Not a block device: $K_TARGET_DEV"; exit 1; }
[ -b "$K_TARGET_DTB_DEV" ]  || { log "ERROR: Not a block device: $K_TARGET_DTB_DEV"; exit 1; }

sync

log "Setting bootloader active slot to $K_INACTIVE_SLOT"
if nvbootctrl -t bootloader set-active-boot-slot "$K_INACTIVE_SLOT"; then
  log "Bootloader active slot set to $K_INACTIVE_SLOT"
else
  log "ERROR: Failed to set bootloader active slot"
  exit 1
fi

NEW="$(nvbootctrl -t bootloader get-current-slot 2>/dev/null || echo unknown)"
log "nvbootctrl reports current bootloader slot: $NEW (takes effect after reboot on some platforms)"

rm -f "$VARS_FILE" || true
log "Post-install complete."
exit 0
