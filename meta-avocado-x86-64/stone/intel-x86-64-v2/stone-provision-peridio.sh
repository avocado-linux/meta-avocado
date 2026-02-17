#!/usr/bin/env bash

# Peridio / swupdate Provisioning Script for Intel x86-64
#
# Creates an swupdate archive (.swu) from stone output for OTA updates
# via Peridio. The .swu contains the rootfs image and pre/post install
# scripts for A/B partition switching.
#
# Environment variables provided by avocado/stone:
# AVOCADO_STONE_MANIFEST  - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR  - stone data directory

set -e
set -u
set -o pipefail

MANIFEST="$AVOCADO_STONE_MANIFEST"
DATA_DIR="$AVOCADO_STONE_DATA_DIR"
BUILD_DIR="$AVOCADO_STONE_BUILD_DIR"

PLATFORM=$(jq -r '.runtime.platform' "$MANIFEST")
ROOTFS_IMAGE=$(jq -r '.storage_devices.rootdisk.images.rootfs' "$MANIFEST")

OUTDIR="${BUILD_DIR}/peridio"
mkdir -p "$OUTDIR"

echo "=== Generating Peridio swupdate image for ${PLATFORM} ==="
echo "  Output directory: ${OUTDIR}"

# =============================================================================
# Validate inputs
# =============================================================================

if [ ! -f "${DATA_DIR}/${ROOTFS_IMAGE}" ]; then
    echo "ERROR: Rootfs image not found: ${DATA_DIR}/${ROOTFS_IMAGE}"
    exit 1
fi

# =============================================================================
# Create swupdate assembly directory
# =============================================================================

SWU_DIR="${BUILD_DIR}/swupdate"
rm -rf "${SWU_DIR}"
mkdir -p "$SWU_DIR"

echo "=== Collecting files for swupdate image ==="

# Copy rootfs image
cp "${DATA_DIR}/${ROOTFS_IMAGE}" "${SWU_DIR}/avocado-image-rootfs.squashfs"
echo "  Rootfs: ${ROOTFS_IMAGE}"

# Copy pre/post install scripts from deploy directory
for script in rootfs-pre.sh rootfs-post.sh; do
    if [ -f "${DATA_DIR}/${script}" ]; then
        cp "${DATA_DIR}/${script}" "${SWU_DIR}/${script}"
        echo "  Script: ${script}"
    else
        echo "  WARNING: ${script} not found in data directory"
    fi
done

# =============================================================================
# Generate sw-description
# =============================================================================
echo "=== Generating sw-description ==="

# Get version info
VERSION=$(grep "^VERSION_ID=" "${DATA_DIR}/os-release" 2>/dev/null | cut -d= -f2 | tr -d '"' || echo "0.1.0")

SW_DESC="${SWU_DIR}/sw-description"

cat > "$SW_DESC" <<EOF
software = {
    version = "${VERSION}";
    hardware-compatibility: [ "${VERSION}" ];
    reboot = true;

    /* OS rootfs - written to inactive A/B partition */
    images: (
        { filename = "avocado-image-rootfs.squashfs"; type = "raw"; device = "/tmp/target_rootfs"; }
    );

    /* Pre/post install scripts for A/B partition switching */
    scripts: (
EOF

[ -f "${SWU_DIR}/rootfs-pre.sh" ] && echo '        { filename = "rootfs-pre.sh";  type = "preinstall";  },'  >> "$SW_DESC"
[ -f "${SWU_DIR}/rootfs-post.sh" ] && echo '        { filename = "rootfs-post.sh"; type = "postinstall"; },' >> "$SW_DESC"

cat >> "$SW_DESC" <<EOF
    );
}
EOF

echo "  Generated sw-description"

# =============================================================================
# Build .swu archive (sw-description must be first entry)
# =============================================================================
echo "=== Building swupdate image ==="

SWU_FILE="${OUTDIR}/avocado-image-${PLATFORM}.swu"

FILE_LIST="${SWU_DIR}/file_list.txt"
(
    cd "$SWU_DIR"
    echo "./sw-description" > "$FILE_LIST"
    find . -type f ! -name "sw-description" ! -name "file_list.txt" -print | sort >> "$FILE_LIST"
)

(
    cd "$SWU_DIR"
    cpio -ov -H crc < "$FILE_LIST" > "$SWU_FILE"
)

echo "  Created: ${SWU_FILE}"
echo "  Size: $(du -h "$SWU_FILE" | cut -f1)"

# =============================================================================
# Delegate to common Peridio provisioning
# =============================================================================

if [ -f "${AVOCADO_RUNTIME_BUILD_DIR:-}/peridio-provision.sh" ]; then
    echo "=== Delegating to common Peridio provisioning ==="
    exec "${AVOCADO_RUNTIME_BUILD_DIR}/peridio-provision.sh" --avocado-os "$SWU_FILE" --installer-type swupdate
else
    echo ""
    echo "=== swupdate archive ready ==="
    echo "  ${SWU_FILE}"
    echo ""
    echo "Upload this .swu file to Peridio for OTA distribution,"
    echo "or apply locally with: swupdate -i ${SWU_FILE}"
fi
