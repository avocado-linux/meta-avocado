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

# Collect extensions
echo "=== Collecting extension images ==="
EXT_SOURCES="${AVOCADO_PREFIX}/output/extensions"
EXT_LIST="${AVOCADO_EXT_LIST:-}"

if [ -z "$EXT_LIST" ]; then
    echo "WARNING: AVOCADO_EXT_LIST is empty or not set; no extensions will be copied"
else
    if [ ! -d "$EXT_SOURCES" ]; then
        echo "WARNING: Extension directory not found: $EXT_SOURCES"
    else
        echo "  Using extension directory: $EXT_SOURCES"
        for ext_name in $EXT_LIST; do
            case "$ext_name" in
                *.raw) ext_file="$ext_name" ;;
                *)     ext_file="${ext_name}.raw" ;;
            esac
            src="${EXT_SOURCES}/${ext_file}"
            if [ -f "$src" ]; then
                cp "$src" "${OUTDIR}/${ext_file}"
                echo "  Copied extension: ${ext_file} -> ${OUTDIR}"
            else
                echo "WARNING: Extension image not found: ${src}"
            fi
        done
    fi
fi

# Generate sw-description file
echo "=== Generating sw-description file ==="
SW_DESC="${SWU_DIR}/sw-description"

# Get version info from os-release or manifest
VERSION=$(grep "^VERSION_ID=" "${DATA_DIR}/os-release" 2>/dev/null | cut -d= -f2 | tr -d '"' || echo "0.1.0")
PLATFORM=$(jq -r '.runtime.platform' "$MANIFEST")

cat > "$SW_DESC" << EOF
software = {
    version = "${VERSION}";
    hardware-compatibility: [ "${VERSION}" ];
    reboot = true;

    /* OS rootfs only */
    images: (
        { filename = "avocado-image-rootfs.squashfs"; type = "raw"; device = "/tmp/target_rootfs"; }
    );

    /* Pre/post install scripts in running order */
    scripts: (
EOF

[ -f "${SWU_DIR}/rootfs-pre.sh" ] && echo '        { filename = "rootfs-pre.sh";  type = "preinstall";  },'  >> "$SW_DESC"
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
    echo "./sw-description" > "$FILE_LIST"
    find . -type f ! -name "sw-description" ! -name "file_list.txt" -print | sort >> "$FILE_LIST"
)

(
    cd "$SWU_DIR"
    cat "$FILE_LIST" | cpio -ov -H crc > "$SWU_FILE"
)

echo "  Created swupdate image: $SWU_FILE"

echo "=== Peridio provisioning complete ==="
echo "Output files in $OUTDIR:"
echo "  - $(basename "$SWU_FILE")"
for f in "${OUTDIR}"/*.raw; do
    [ -f "$f" ] && echo "  - $(basename "$f")"
done

