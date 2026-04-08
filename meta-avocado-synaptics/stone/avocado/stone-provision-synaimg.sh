#!/usr/bin/env bash
set -euo pipefail

# Environment variables provided by avocado:
# AVOCADO_STONE_MANIFEST - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory (input artifacts)
# AVOCADO_STONE_DATA_DIR - stone data directory
# AVOCADO_PROVISION_OUT  - output directory for the SYNAIMG folder

# ---------------------------------------------------------------------------
# Read machine / image names from the stone manifest
# ---------------------------------------------------------------------------
MACHINE=$(jq -r .runtime.platform "${AVOCADO_STONE_MANIFEST}")
ROOTFS_IMAGE=$(jq -r .storage_devices.rootdisk.images.rootfs "${AVOCADO_STONE_MANIFEST}")
VAR_IMAGE=$(jq -r .storage_devices.rootdisk.images.var "${AVOCADO_STONE_MANIFEST}")
BOOTLOADER_IMAGE=$(jq -r .storage_devices.rootdisk.images.bootloader "${AVOCADO_STONE_MANIFEST}")
BOOT_IMAGE=$(jq -r .storage_devices.rootdisk.images.boot "${AVOCADO_STONE_MANIFEST}")

BUILD_DIR="${AVOCADO_STONE_BUILD_DIR}"
OUT_DIR="${AVOCADO_PROVISION_OUT:-${BUILD_DIR}/SYNAIMG}"

# ---------------------------------------------------------------------------
# Verify required tools
# ---------------------------------------------------------------------------
for tool in gzip img2simg jq; do
    if ! command -v "${tool}" &>/dev/null; then
        echo "ERROR: required tool '${tool}' not found in PATH" >&2
        exit 1
    fi
done

# ---------------------------------------------------------------------------
# Derive zip path and fallback directory
# ---------------------------------------------------------------------------
ROOTDISK_ZIP=$(jq -r '.storage_devices.rootdisk.out' "${AVOCADO_STONE_MANIFEST}")
ZIP_PATH="${BUILD_DIR}/${ROOTDISK_ZIP}"
FALLBACK_DIR="$(realpath "${AVOCADO_STONE_DATA_DIR}/../../../../runtimes/dev")"

# ---------------------------------------------------------------------------
# Prepare input files: extract from zip, fall back to runtimes/dev for the rest
# ---------------------------------------------------------------------------
if [ -f "${ZIP_PATH}" ]; then
    echo "Extracting images from ${ZIP_PATH}..."
    unzip -p "${ZIP_PATH}" data/bootloader.img > "${BUILD_DIR}/${BOOTLOADER_IMAGE}"
    unzip -p "${ZIP_PATH}" data/boot.img       > "${BUILD_DIR}/${BOOT_IMAGE}"
    unzip -p "${ZIP_PATH}" data/rootfs.img     > "${BUILD_DIR}/${ROOTFS_IMAGE}"
    unzip -p "${ZIP_PATH}" data/var.img        > "${BUILD_DIR}/${VAR_IMAGE}"
else
    echo "WARNING: zip not found at ${ZIP_PATH}" >&2
fi

for f in firmware.subimg key.subimg preboot.subimg tee.subimg emmc_image_list emmc_part_list fastlogo.subimg.gz; do
    if [ ! -f "${BUILD_DIR}/${f}" ] && [ -f "${FALLBACK_DIR}/${f}" ]; then
        cp "${FALLBACK_DIR}/${f}" "${BUILD_DIR}/${f}"
    fi
done

# ---------------------------------------------------------------------------
# Rename 'home' partition to 'var' in emmc list files
# ---------------------------------------------------------------------------
sed -i 's/home/var/g' "${BUILD_DIR}/emmc_part_list"
sed -i 's/home/var/g' "${BUILD_DIR}/emmc_image_list"

# ---------------------------------------------------------------------------
# Verify all input files are present before doing any work
# ---------------------------------------------------------------------------
missing=0
for f in \
    "${BUILD_DIR}/${BOOTLOADER_IMAGE}" \
    "${BUILD_DIR}/${BOOT_IMAGE}" \
    "${BUILD_DIR}/${ROOTFS_IMAGE}" \
    "${BUILD_DIR}/${VAR_IMAGE}" \
    "${BUILD_DIR}/firmware.subimg" \
    "${BUILD_DIR}/key.subimg" \
    "${BUILD_DIR}/preboot.subimg" \
    "${BUILD_DIR}/tee.subimg" \
    "${BUILD_DIR}/emmc_image_list" \
    "${BUILD_DIR}/emmc_part_list" \
    "${BUILD_DIR}/fastlogo.subimg.gz"
do
    if [ ! -f "${f}" ]; then
        echo "ERROR: missing input file: ${f}" >&2
        missing=1
    fi
done
[ "${missing}" -eq 0 ] || exit 1

# ---------------------------------------------------------------------------
# Create output directory
# ---------------------------------------------------------------------------
echo "Creating SYNAIMG in: ${OUT_DIR}"
rm -rf "${OUT_DIR}"
mkdir -p "${OUT_DIR}"

# Tag file (mirrors the TAG--<image-name>--TAG file written by image_synaimg.bbclass)
touch "${OUT_DIR}/TAG--${MACHINE}--TAG"

# ---------------------------------------------------------------------------
# Static copies (already in their final form)
# ---------------------------------------------------------------------------
cp "${BUILD_DIR}/emmc_image_list"   "${OUT_DIR}/"
cp "${BUILD_DIR}/emmc_part_list"    "${OUT_DIR}/"
sed -i 's/home/var/g' "${OUT_DIR}/emmc_part_list"
sed -i 's/home/var/g' "${OUT_DIR}/emmc_image_list"
sed -i 's/rootfs\.subimg\.gz/rootfs_s.subimg/g' "${OUT_DIR}/emmc_image_list"
sed -i 's/var\.subimg\.gz/var_s.subimg/g' "${OUT_DIR}/emmc_image_list"
cp "${BUILD_DIR}/fastlogo.subimg.gz" "${OUT_DIR}/"

# ---------------------------------------------------------------------------
# Gzip-compressed sub-images
#   <source>                  →  <dest in SYNAIMG>
#   bootloader.subimg         →  bl.subimg.gz
#   linux_bootimgs.subimg     →  boot.subimg.gz
#   firmware.subimg           →  firmware.subimg.gz
#   key.subimg                →  key.subimg.gz
#   preboot.subimg            →  preboot.subimg.gz
#   tee.subimg                →  tzk.subimg.gz
# ---------------------------------------------------------------------------
echo "Compressing sub-images..."
gzip -1 -c "${BUILD_DIR}/${BOOTLOADER_IMAGE}"  > "${OUT_DIR}/bl.subimg.gz"
gzip -1 -c "${BUILD_DIR}/${BOOT_IMAGE}"        > "${OUT_DIR}/boot.subimg.gz"
gzip -1 -c "${BUILD_DIR}/firmware.subimg"      > "${OUT_DIR}/firmware.subimg.gz"
gzip -1 -c "${BUILD_DIR}/key.subimg"           > "${OUT_DIR}/key.subimg.gz"
gzip -1 -c "${BUILD_DIR}/preboot.subimg"       > "${OUT_DIR}/preboot.subimg.gz"
gzip -1 -c "${BUILD_DIR}/tee.subimg"           > "${OUT_DIR}/tzk.subimg.gz"

# ---------------------------------------------------------------------------
# Rootfs erofs-lz4 image:
#   1. Compress directly → rootfs.subimg.gz  (for flash via .gz path)
#   2. Convert to Android sparse → rootfs_s.subimg  (for flash via sparse path)
# ---------------------------------------------------------------------------
echo "Processing rootfs image (${ROOTFS_IMAGE})..."
gzip -1 -c "${BUILD_DIR}/${ROOTFS_IMAGE}" > "${OUT_DIR}/rootfs.subimg.gz"
img2simg "${BUILD_DIR}/${ROOTFS_IMAGE}" "${OUT_DIR}/rootfs_s.subimg" 4096

# ---------------------------------------------------------------------------
# Var btrfs image:
#   Convert to Android sparse → var_s.subimg
# ---------------------------------------------------------------------------
echo "Processing var image (${VAR_IMAGE})..."
img2simg "${BUILD_DIR}/${VAR_IMAGE}" "${OUT_DIR}/var_s.subimg" 4096

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo "SYNAIMG contents:"
ls -lh "${OUT_DIR}/"
