#!/usr/bin/env bash

set -euo pipefail

# Environment variables provided by stone:
# AVOCADO_STONE_MANIFEST - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR - stone data directory
# AVOCADO_DEVICE_CERT - device certificate content (base64 encoded pem)
# AVOCADO_DEVICE_KEY - device private key content (base64 encoded pem)
# AVOCADO_DEVICE_ID - device ID
# AVOCADO_PROVISION_FORCE - 1, 0 or unset; see avocado_safe_disk_confirm
# AVOCADO_PROVISION_DRY_RUN - 1 runs every check and prints the uuu command
#                             instead of running it
# AVOCADO_PROVISION_FWUP_TASK - only complete; upgrade is refused (uuu rewrites
#                             the whole eMMC and has no upgrade path)

# Confirmation table and run-mode validation shared with the other profiles.
# Shipped beside this script (the manifest lists it under provision.files).
# shellcheck source=/dev/null # sibling file, absent from a standalone lint
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/avocado-safe-disk.sh"

# Checked first so a bad value, or a task this profile cannot do, stops the run
# before any image work and before waiting for a device.
avocado_safe_disk_modes uuu-emmc 1 0 || exit 1

echo "=== iMX eMMC Provisioning via uuu ==="
echo "Manifest: $AVOCADO_STONE_MANIFEST"
echo "Data dir: $AVOCADO_STONE_DATA_DIR"
echo "Build dir: $AVOCADO_STONE_BUILD_DIR"

# --- Step 1: Build the raw disk image from the fwup archive ---
archive_name=$(jq -r .storage_devices.rootdisk.out "$AVOCADO_STONE_MANIFEST")
archive_file="${AVOCADO_STONE_BUILD_DIR}/${archive_name}"
archive_image="${archive_file%.*}.img"

if [ "${AVOCADO_PROVISION_DRY_RUN:-}" = "1" ]; then
  echo "dry-run: would build ${archive_image} from ${archive_file} unless it exists"
elif [ ! -f "$archive_image" ]; then
  echo "Building disk image from archive..."
  fwup \
    -a \
    -i "${archive_file}" \
    -d "${archive_image}" \
    -t complete
  echo "Disk image created: $archive_image"
else
  echo "Using existing disk image: $archive_image"
fi

# --- Step 2: Read per-machine eMMC parameters from manifest ---
# emmc_uboot_dev: U-Boot mmc device number (e.g. 2 on iMX8MP EVK, 0 on iMX93 FRDM)
# emmc_mmcblk:    Linux mmcblkN block device number for eMMC
profile_config_path='.provision.profiles."uuu-emmc".config'
emmc_uboot_dev=$(jq -r "${profile_config_path}.emmc_uboot_dev // empty" "$AVOCADO_STONE_MANIFEST")
emmc_mmcblk=$(jq -r "${profile_config_path}.emmc_mmcblk // empty" "$AVOCADO_STONE_MANIFEST")
if [ -z "$emmc_uboot_dev" ] || [ -z "$emmc_mmcblk" ]; then
  echo "ERROR: provision.profiles.uuu-emmc.config must define emmc_uboot_dev and emmc_mmcblk"
  exit 1
fi

# --- Step 3: Patch U-Boot env to point root/devnum at eMMC ---
echo "Patching U-Boot environment for eMMC boot (devnum=${emmc_uboot_dev}, mmcblk=${emmc_mmcblk})..."

fw_env_img_config="${AVOCADO_STONE_BUILD_DIR}/fw_env_img.config"
cat >"$fw_env_img_config" <<EOF
${archive_image}	0x400000	0x20000	0x200	256
${archive_image}	0x440000	0x20000	0x200	256
EOF

if [ "${AVOCADO_PROVISION_DRY_RUN:-}" = "1" ]; then
  echo "dry-run: would set U-Boot env devnum=${emmc_uboot_dev} mmcblk=${emmc_mmcblk} in ${archive_image}"
else
  fw_setenv -c "$fw_env_img_config" devnum "$emmc_uboot_dev"
  fw_setenv -c "$fw_env_img_config" mmcblk "$emmc_mmcblk"
  echo "U-Boot env patched: devnum=${emmc_uboot_dev}, mmcblk=${emmc_mmcblk}"
fi

# --- Step 4: Locate imx-boot image for the SDPS handoff ---
# iMX8M: prefer the emmc_fastboot variant (mkimage_imx8 -dev emmc_fastboot),
#        which configures the legacy boot container for USB→fastboot handoff.
# iMX9:  AHAB-based flash_singleboot is reused directly; U-Boot enters fastboot
#        via CONFIG_FASTBOOT_UUU_SUPPORT, no separate variant exists.
imx_boot_name=$(jq -r '.storage_devices.rootdisk.images.imx_boot_emmc_fastboot // empty' "$AVOCADO_STONE_MANIFEST")
if [ -z "$imx_boot_name" ]; then
  imx_boot_name=$(jq -r '.storage_devices.rootdisk.images.imx_boot // empty' "$AVOCADO_STONE_MANIFEST")
fi
if [ -z "$imx_boot_name" ]; then
  echo "ERROR: no imx_boot image specified in manifest"
  exit 1
fi

imx_boot_path="${AVOCADO_STONE_DATA_DIR}/${imx_boot_name}"
if [ ! -f "$imx_boot_path" ]; then
  echo "ERROR: imx-boot not found at $imx_boot_path"
  exit 1
fi
echo "Using imx-boot: $imx_boot_path"

# --- Step 5: Wait for exactly one device in serial download mode, and pin it ---
# NXP i.MX devices in serial download mode use USB vendor IDs:
#   1fc9 (NXP) or 15a2 (Freescale legacy)
#
# Matching a vendor ID only answers "is any NXP device in serial download
# mode", and uuu without -m takes whichever known device enumerated first. With
# a second i.MX board on the bench that is the wrong board, so the target is
# pinned: exactly one device, passed to uuu by its own path.
nxp_lsusb_lines() {
  lsusb 2>/dev/null | grep -Ei ' ID (1fc9|15a2):[0-9a-f]{4}' || true
}

check_sdp() {
  [ -n "$(nxp_lsusb_lines)" ]
}

# uuu -m takes the path column of `uuu -lsusb` (bus:port chain, e.g. 1:2 or
# 3:1-4), which is not the device number lsusb prints, so it is read from uuu.
# Output per device: "<path> <chip> <protocol> <vid:pid>".
uuu_known_devices() {
  uuu -lsusb 2>/dev/null \
    | awk '$1 ~ /^[0-9]+:[0-9]+([.-][0-9]+)*$/ {
      vid = $4; pid = $5; sub(/^0x/, "", vid); sub(/^0x/, "", pid)
      print $1, $2, $3, vid ":" pid
    }' || true
}

if check_sdp; then
  echo "Device detected in serial download mode"
else
  echo "Please put device into serial download mode..."
  echo "(Set the board's boot-mode switches to serial download and power-cycle; see the board user manual for the exact positions)"
  # shellcheck disable=SC2034 # i is a bare 60-iteration counter; the loop
  # polls check_sdp and never reads the index.
  for i in $(seq 1 60); do
    if check_sdp; then
      echo "Device detected in serial download mode"
      break
    fi
    sleep 1
  done
  if ! check_sdp; then
    echo "ERROR: No NXP device detected in serial download mode (waited 60s)"
    echo "       Set the board's boot-mode switches to serial download, power-cycle it,"
    echo "       and connect its USB download port to this host."
    exit 1
  fi
fi

sdp_lines=$(nxp_lsusb_lines)
sdp_count=$(printf '%s\n' "$sdp_lines" | grep -c . || true)
uuu_devices=$(uuu_known_devices)
uuu_count=$(printf '%s\n' "$uuu_devices" | grep -c . || true)

if [ "$sdp_count" -gt 1 ]; then
  echo "ERROR: $sdp_count NXP devices are in serial download mode:"
  if [ "$uuu_count" -gt 0 ]; then
    printf '%s\n' "$uuu_devices" | sed 's/^/  USB path /'
  fi
  printf '%s\n' "$sdp_lines" | sed 's/^/  lsusb: /'
  echo "       uuu would take whichever enumerated first, so refusing rather than guessing."
  echo "       Leave exactly one board in serial download mode and run again."
  exit 1
fi

if [ "$uuu_count" -ne 1 ]; then
  echo "ERROR: lsusb shows one NXP device but uuu recognises $uuu_count:"
  printf '%s\n' "$sdp_lines" | sed 's/^/  lsusb: /'
  if [ "$uuu_count" -gt 0 ]; then
    printf '%s\n' "$uuu_devices" | sed 's/^/  USB path /'
  fi
  echo "       uuu cannot be pinned to a device it does not list. Check that this user"
  echo "       can open the USB device (see 'uuu -udev') and that the device is a known i.MX."
  exit 1
fi

read -r usb_path usb_chip usb_proto usb_id <<<"$uuu_devices"

# --- Step 5b: Confirm the target ---
# The retype target is the uuu USB path, the only name that selects the board
# (uuu -m); lsusb bus/device numbers are never accepted. FORCE only skips the
# retype: two boards were refused above whatever FORCE says.
echo "Target device: USB ${usb_path} ${usb_id} (${usb_chip}, ${usb_proto})"
echo "About to ERASE the eMMC (U-Boot mmc dev ${emmc_uboot_dev}) on this board."
avocado_safe_disk_confirm "$usb_path" || exit 1

# --- Step 6: Generate custom uuu script and flash ---
# uuu resolves file paths relative to the .uuu script location,
# so we symlink/copy files into the build dir and use bare filenames.
uuu_dir="${AVOCADO_STONE_BUILD_DIR}/uuu"
mkdir -p "$uuu_dir"

ln -sf "$imx_boot_path" "$uuu_dir/imx-boot"
ln -sf "$archive_image" "$uuu_dir/rootdisk.img"

# Standard imx-boot (non-fastboot variant) for writing to the eMMC boot
# partition. On iMX8M this differs from the SDPS payload; on iMX9 they are
# the same image. Always link it so the .uuu script can reference it.
imx_boot_sd_name=$(jq -r '.storage_devices.rootdisk.images.imx_boot // empty' "$AVOCADO_STONE_MANIFEST")
if [ -n "$imx_boot_sd_name" ]; then
  ln -sf "${AVOCADO_STONE_DATA_DIR}/${imx_boot_sd_name}" "$uuu_dir/imx-boot-sd"
else
  ln -sf "$imx_boot_path" "$uuu_dir/imx-boot-sd"
fi

uuu_script="${uuu_dir}/flash_emmc.uuu"
cat >"$uuu_script" <<EOF
uuu_version 1.2.39

# Boot U-Boot via SDPS
SDPS: boot -f imx-boot

# SPL hand-off. An SPL built to boot from USB SDP (U-Boot 2026.04 on i.MX 95:
# "Trying to boot from USB SDP ... SDP: handle requests") re-enumerates as the
# SDPV device (1fc9:0151) and waits for the host to push U-Boot proper; without
# this block both sides wait forever. uuu runs a protocol block only when a
# matching device appears, so on an SPL that streams the second stage through
# the ROM API instead (i.MX 93) these lines are skipped -- same shape as uuu's
# built-in emmc_all script.
SDPV: delay 1000
SDPV: write -f imx-boot -skipspl
SDPV: jump

# U-Boot enters fastboot mode (iMX8M: -dev emmc_fastboot container;
# iMX9: CONFIG_FASTBOOT_UUU_SUPPORT in U-Boot). Select eMMC as the target.
FB: ucmd setenv fastboot_dev mmc
FB: ucmd setenv mmcdev ${emmc_uboot_dev}
FB: ucmd mmc dev ${emmc_uboot_dev}

# Write the raw disk image to eMMC user data area
FB[-t 600000]: flash -raw2sparse all rootdisk.img

# Write imx-boot to the eMMC hardware boot partition.
# This replaces any factory bootloader and ensures our U-Boot is used on next boot.
FB: flash bootloader imx-boot-sd

# Configure eMMC to boot from boot partition 1 (ack=0, boot_partition=1, access=0)
FB: ucmd if env exists emmc_ack; then ; else setenv emmc_ack 0; fi;
FB: ucmd mmc partconf ${emmc_uboot_dev} \${emmc_ack} 1 0

FB: done
EOF

echo "Flashing to eMMC via uuu..."
echo "  Bootloader: $imx_boot_path"
echo "  Disk image: $archive_image"
echo "  eMMC dev: $emmc_uboot_dev"
echo "  Script: $uuu_script"
echo ""
cat "$uuu_script"
echo ""

if [ "${AVOCADO_PROVISION_DRY_RUN:-}" = "1" ]; then
  # Same command line a real run uses, printed and never executed.
  avocado_safe_disk_write uuu -v -m "$usb_path" "$uuu_script"
  avocado_safe_disk_finish "$usb_path"
  exit 0
fi

uuu -v -m "$usb_path" "$uuu_script"

echo "=== eMMC provisioning complete ==="
