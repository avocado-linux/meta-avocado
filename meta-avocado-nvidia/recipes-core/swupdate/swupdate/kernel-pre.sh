#!/bin/sh
# Pre-install for Tegra A/B kernel+dtb updates (cboot slots)
set -e

LOGFILE="/tmp/swupdate-tegra-ab.log"
VARS_FILE="/tmp/tegra-ab-kernel.vars"
KERNEL_SYMLINK="/tmp/target_kernel"
DTB_SYMLINK="/tmp/target_dtb"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [kernel-pre] $*" | tee -a "$LOGFILE"; }

resolve_partlabel() {
    label="$1"
    bylabel="/dev/disk/by-partlabel/$label"
    if [ -L "$bylabel" ]; then
        real="$(readlink -f "$bylabel" || true)"
        [ -n "$real" ] && [ -b "$real" ] && { echo "$real"; return 0; }
    fi
    real="$(blkid -l -t "PARTLABEL=$label" -o device 2>/dev/null | head -n1 || true)"
    [ -n "$real" ] && [ -b "$real" ] && { echo "$real"; return 0; }
    return 1
}

log "=== Kernel/DTB Pre-install ==="

command -v nvbootctrl >/dev/null 2>&1 || { log "ERROR: nvbootctrl not found"; exit 1; }
command -v udevadm >/dev/null 2>&1 && udevadm settle || true

CUR="$(nvbootctrl -t bootloader get-current-slot 2>/dev/null | tr -d '[:space:]')"
[ -n "$CUR" ] || { log "ERROR: Unable to get current bootloader slot"; exit 1; }
case "$CUR" in
  0) INACTIVE=1; K_LABEL="B_kernel"; DTB_LABEL="B_kernel-dtb"; ACTIVE_K="A_kernel"; ACTIVE_DTB="A_kernel-dtb";;
  1) INACTIVE=0; K_LABEL="A_kernel"; DTB_LABEL="A_kernel-dtb"; ACTIVE_K="B_kernel"; ACTIVE_DTB="B_kernel-dtb";;
  *) log "ERROR: Unexpected slot value '$CUR'"; exit 1;;
esac
log "Current bootloader slot: $CUR  -> inactive: $INACTIVE"
log "Target labels: $K_LABEL / $DTB_LABEL"

K_DEV="$(resolve_partlabel "$K_LABEL" || true)"
DTB_DEV="$(resolve_partlabel "$DTB_LABEL" || true)"
[ -n "$K_DEV" ]  || { log "ERROR: Cannot resolve $K_LABEL"; exit 1; }
[ -n "$DTB_DEV" ]|| { log "ERROR: Cannot resolve $DTB_LABEL"; exit 1; }
log "Resolved: $K_LABEL -> $K_DEV ; $DTB_LABEL -> $DTB_DEV"

# Create/update symlinks used by sw-description devices
rm -f "$KERNEL_SYMLINK" "$DTB_SYMLINK"
ln -s "$K_DEV"  "$KERNEL_SYMLINK"
ln -s "$DTB_DEV" "$DTB_SYMLINK"
log "Symlinks: $KERNEL_SYMLINK -> $K_DEV ; $DTB_SYMLINK -> $DTB_DEV"

# Export variables for postinstall
{
  echo "K_INACTIVE_SLOT=$INACTIVE"
  echo "K_TARGET_DEV=$K_DEV"
  echo "K_TARGET_DTB_DEV=$DTB_DEV"
  echo "K_TARGET_LABEL=$K_LABEL"
  echo "K_TARGET_DTB_LABEL=$DTB_LABEL"
} > "$VARS_FILE"

log "Pre-install complete."
exit 0
