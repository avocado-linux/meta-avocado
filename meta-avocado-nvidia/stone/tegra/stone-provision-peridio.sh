#!/usr/bin/env bash

# Exit immediately if any command fails
set -e
# Exit on undefined variables
set -u
# Propagate errors in pipelines
set -o pipefail

# Environment variables provided by avocado/stone:
# AVOCADO_STONE_MANIFEST - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR - stone data directory

OUTDIR="${AVOCADO_STONE_BUILD_DIR}/peridio"
mkdir -p "$OUTDIR"

echo "=== Generating Peridio swupdate image ==="
echo "Output directory: $OUTDIR"

# Read manifest to get image information
MANIFEST="$AVOCADO_STONE_MANIFEST"
DATA_DIR="$AVOCADO_STONE_DATA_DIR"
BUILD_DIR="$AVOCADO_STONE_BUILD_DIR"

# Extract image names from manifest
ROOTFS_IMAGE=$(jq -r '.storage_devices.rootdisk.images.rootfs' "$MANIFEST")

# Get tegraflash image name from manifest
TEGRAFLASH_IMAGE=$(jq -r '.storage_devices.rootdisk.images.tegraflash' "$MANIFEST")
TEGRAFLASH_FILE="${DATA_DIR}/${TEGRAFLASH_IMAGE}"

# Create temporary directory for swupdate assembly
SWU_DIR="${BUILD_DIR}/swupdate"
rm -rf "${SWU_DIR}"
mkdir -p "$SWU_DIR"

echo "=== Collecting files for swupdate image ==="

if [ -f "$TEGRAFLASH_FILE" ]; then
    TMP_EXTRACT=$(mktemp -d)
    trap "rm -rf '$TMP_EXTRACT'" EXIT
    
    tar -xzf "$TEGRAFLASH_FILE" -C "$TMP_EXTRACT" 2>/dev/null || true

    # Copy swupdate scripts
    for script in rootfs-pre.sh rootfs-post.sh; do
        if [ -f "${TMP_EXTRACT}/${script}" ]; then
            cp "${TMP_EXTRACT}/${script}" "${SWU_DIR}/${script}"
            echo "  Found ${script}"
        else
            echo "WARNING: ${script} not found"
        fi
    done
    
    rm -rf "$TMP_EXTRACT"
    trap - EXIT
fi

# Copy rootfs image
if [ -f "${DATA_DIR}/${ROOTFS_IMAGE}" ]; then
    cp "${DATA_DIR}/${ROOTFS_IMAGE}" "${SWU_DIR}/avocado-image-rootfs.squashfs"
    echo "  Found rootfs: ${ROOTFS_IMAGE}"
else
    echo "ERROR: Rootfs image not found: ${DATA_DIR}/${ROOTFS_IMAGE}"
    exit 1
fi

# Collect extension raw images
echo "=== Collecting extension images ==="
EXT_DIR="${SWU_DIR}/extensions"
mkdir -p "$EXT_DIR"

# Find all .raw extension files in the extensions output directory
EXT_SOURCES="${AVOCADO_PREFIX}/output/extensions"

EXT_COUNT=0
if [ -d "$EXT_SOURCES" ]; then
    echo "  Checking extension directory: $EXT_SOURCES"
    for ext_file in "$EXT_SOURCES"/*.raw; do
        if [ -f "$ext_file" ]; then
            EXT_NAME=$(basename "$ext_file")
            cp "$ext_file" "${SWU_DIR}/${EXT_NAME}"
            echo "  Found ${EXT_NAME}"
            EXT_COUNT=$((EXT_COUNT + 1))
        fi
    done
fi

if [ $EXT_COUNT -eq 0 ]; then
    echo "WARNING: No extension images found"
fi

# Generate sw-description file
echo "=== Generating sw-description file ==="
SW_DESC="${SWU_DIR}/sw-description"

# Get version info from os-release or manifest
VERSION=$(grep "^VERSION_ID=" "${DATA_DIR}/os-release" 2>/dev/null | cut -d= -f2 | tr -d '"' || echo "0.1.0")
PLATFORM=$(jq -r '.runtime.platform' "$MANIFEST")

# Start building sw-description
cat > "$SW_DESC" << EOF
software = {
    version = "${VERSION}";
    hardware-compatibility: [ "${VERSION}" ];
    reboot = true;

    /* OS files + extensions */
    images: (
EOF

# Add rootfs
cat >> "$SW_DESC" << EOF
        /* Rootfs */
        { filename = "avocado-image-rootfs.squashfs"; type = "raw"; device = "/tmp/target_rootfs"; },
EOF

# Add extension images
for ext_file in "${SWU_DIR}"/*.raw; do
    if [ -f "$ext_file" ]; then
        EXT_NAME=$(basename "$ext_file")
        EXT_BASENAME=$(basename "$ext_file" .raw)
        cat >> "$SW_DESC" << EOF
        /* Extension */
        { filename = "${EXT_NAME}"; path = "/var/lib/avocado/extensions/${EXT_NAME}";
          type = "rawfile"; properties = { create-destination = "true"; atomic-install = "true"; }; },
EOF
    fi
done

# Add scripts section
cat >> "$SW_DESC" << EOF
    );

    /* Pre/post install scripts in running order */
    scripts: (
EOF

# Add scripts in running order
[ -f "${SWU_DIR}/rootfs-pre.sh" ] && echo '        { filename = "rootfs-pre.sh";  type = "preinstall";  },' >> "$SW_DESC"
[ -f "${SWU_DIR}/rootfs-post.sh" ] && echo '        { filename = "rootfs-post.sh"; type = "postinstall"; },' >> "$SW_DESC"

cat >> "$SW_DESC" << EOF
    );
}
EOF

echo "  Generated sw-description"

# Build swupdate image using cpio
echo "=== Building swupdate image ==="
SWU_FILE="${OUTDIR}/avocado-image-${PLATFORM}.swu"

# Create file list for cpio (sw-description must be first)
FILE_LIST="${SWU_DIR}/file_list.txt"
(
    cd "$SWU_DIR"
    # Write sw-description first
    echo "./sw-description" > "$FILE_LIST"
    # Then append all other files (sorted, excluding sw-description and file_list.txt)
    find . -type f ! -name "sw-description" ! -name "file_list.txt" -print | sort >> "$FILE_LIST"
)

# Build cpio archive
(
    cd "$SWU_DIR"
    cat "$FILE_LIST" | cpio -ov -H crc > "$SWU_FILE"
)

echo "  Created swupdate image: $SWU_FILE"

echo "=== Peridio provisioning complete ==="
echo "Output files:"
echo "  - $(basename "$SWU_FILE")"
echo "Location: $OUTDIR"

