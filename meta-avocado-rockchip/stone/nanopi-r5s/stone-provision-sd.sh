#!/usr/bin/env bash
#
# sd profile for nanopi-r5s: build the GPT disk image, then write it to
# a microSD in a USB reader on the host. Mirrors meta-avocado-renesas's
# rzv2n-sr-som/stone-provision-sd.sh.
#
# The card must already be inserted in the host USB reader before invoking.
# Name it with AVOCADO_PROVISION_DEVICE=/dev/sdX (AVOCADO_SD_DEVICE is an
# alias). With none named, the one disk on a USB or MMC bus is offered, and
# only on a terminal: an unattended run must name its device.
# AVOCADO_PROVISION_FORCE=1 skips the retype and never selects a disk.
# AVOCADO_PROVISION_DRY_RUN=1 runs every guard and prints the write without
# doing it.

set -e
set -u
set -o pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

# Wrong-disk guards shared with the other sd and usb profiles. Shipped beside
# this script (the manifest lists it under provision.files).
# shellcheck source=/dev/null # sibling file, absent from a standalone lint
. "${SCRIPT_DIR}/avocado-safe-disk.sh"

# A dry run goes through the write choke point; only the complete image is
# written, so a task other than complete is refused.
avocado_safe_disk_modes sd 1 0 || exit 1

DISK_IMAGE=$("${SCRIPT_DIR}/build-disk-image.sh")

# Docker Desktop / Windows / macOS: emit the image and let the user flash with
# their host's disk imager. AVOCADO_USB_PASSTHROUGH=0 means the SDK was launched
# without a way to enumerate host block devices.
if [ "${AVOCADO_USB_PASSTHROUGH:-1}" = "0" ]; then
  if [ -z "${AVOCADO_PROVISION_OUT:-}" ]; then
    echo "ERROR: AVOCADO_PROVISION_OUT must be set when USB passthrough is unavailable." >&2
    exit 1
  fi
  mkdir -p "$AVOCADO_PROVISION_OUT"
  cp -v "$DISK_IMAGE" "$AVOCADO_PROVISION_OUT/"
  cat >"$AVOCADO_PROVISION_OUT/.provision-result.json" <<EOF
{
  "host_action": "burn_removable",
  "image": "$(basename "$DISK_IMAGE")"
}
EOF
  cat <<EOF

USB passthrough unavailable. Disk image written to:
  $AVOCADO_PROVISION_OUT/$(basename "$DISK_IMAGE")
Burn it to a microSD with your host OS's disk imager, then insert into the
NanoPi R5S microSD slot and power-cycle.
EOF
  exit 0
fi

sysblock=${AVOCADO_PROVISION_SYSBLOCK:-/sys/class/block}

# Whole disks on a USB or MMC bus, decided by the library's bus check. The
# kernel removable flag is not consulted: it is wrong both ways.
list_bus_candidates() {
  local entry name node
  for entry in "$sysblock"/*; do
    [ -e "$entry" ] || continue
    name=$(basename -- "$entry")
    node="${AVOCADO_SAFE_DISK_DEVDIR:-/dev}/${name}"
    avocado_safe_disk_whole_disk "$node" 2>/dev/null || continue
    avocado_safe_disk_bus "$node" 2>/dev/null || continue
    echo "$node"
  done
}

named=$(avocado_safe_disk_sd_device) || exit 1
if [ -n "$named" ]; then
  target="$named"
else
  # Choosing the target is an answer, and only a terminal answers.
  # AVOCADO_PROVISION_FORCE does not stand in for it.
  if [ ! -t 0 ]; then
    echo "ERROR: no device named and no terminal: cannot choose a target without a terminal." >&2
    echo "Set AVOCADO_PROVISION_DEVICE=/dev/sdX for an unattended run." >&2
    exit 1
  fi
  mapfile -t candidates < <(list_bus_candidates)
  case ${#candidates[@]} in
    0)
      echo "ERROR: no disk on a USB or MMC bus detected. Insert the microSD via a USB reader and re-run." >&2
      exit 1
      ;;
    1)
      target="${candidates[0]}"
      ;;
    *)
      echo "ERROR: multiple disks on a USB or MMC bus detected:" >&2
      printf '  %s\n' "${candidates[@]}" >&2
      echo "Set AVOCADO_PROVISION_DEVICE=/dev/sdX to pick one, or unplug the others." >&2
      exit 1
      ;;
  esac
fi

# Whole disk on a USB or MMC bus that does not hold the running root.
avocado_safe_disk_check_device "$target" || exit 1
target="$AVOCADO_SAFE_DISK_DEV"

cat <<EOF

NanoPi R5S microSD provisioning
  Image:  $(basename "$DISK_IMAGE")
EOF

# Typed retype of the device path, skipped only by AVOCADO_PROVISION_FORCE=1;
# naming the card does not skip it. A dry run asks nothing.
avocado_safe_disk_confirm "$target" || exit 1

# Unmount any auto-mounted partitions before writing.
target_base=$(basename "$target")
for partdir in "$sysblock/$target_base/$target_base"*; do
  [ -e "$partdir" ] || continue
  avocado_safe_disk_write umount "${AVOCADO_SAFE_DISK_DEVDIR:-/dev}/$(basename "$partdir")" 2>/dev/null || true
done

# Whatever is still mounted now was not unmounted above; never write under it.
avocado_safe_disk_unmounted "$target" || exit 1

echo "Writing $(basename "$DISK_IMAGE") to $target..."
# oflag=direct bypasses the page cache so the dd progress meter reflects real
# device throughput (typically 15-30 MB/s on a USB SD reader, not the
# RAM-to-RAM copy speed). With buffered I/O dd "finishes" fast and the script
# appears to hang for minutes inside sync.
avocado_safe_disk_write dd if="$DISK_IMAGE" of="$target" bs=4M oflag=direct status=progress
avocado_safe_disk_write sync

avocado_safe_disk_finish "$target"
if [ "${AVOCADO_PROVISION_DRY_RUN:-}" = "1" ]; then
  exit 0
fi

cat <<EOF

microSD written. Eject the card, insert into the NanoPi R5S, and power on.

The RK3568 BootROM prefers the microSD over eMMC, so a card written this way
takes precedence over whatever is already on the on-board eMMC. U-Boot's
distro_bootcmd probes mmc1 (the microSD slot -- rk3568.dtsi aliases mmc0 to
the eMMC sdhci and mmc1 to sdmmc0), finds /extlinux/extlinux.conf on boot-a,
and loads Image + DTB + initramfs.

Serial console: ttyS2 @ 1500000 baud, on the 3-pin debug header next to the
GPIO header (GND / TX / RX).
EOF
