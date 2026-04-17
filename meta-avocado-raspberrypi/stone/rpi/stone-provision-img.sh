#!/usr/bin/env bash

# Create a raw disk image from the stone build output.
#
# Supports both fwup-based archives (legacy, Pi 0 2W) and tryboot archives
# (Pi 4/5 with sfdisk + dd).

set -euo pipefail

# Environment variables provided by avocado:
# AVOCADO_STONE_MANIFEST - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR - stone data directory
# AVOCADO_DEVICE_CERT - device certificate content (base64 encoded pem)
# AVOCADO_DEVICE_KEY - device private key content (base64 encoded pem)
# AVOCADO_DEVICE_ID - device ID

archive_name=$(jq -r .storage_devices.rootdisk.out "$AVOCADO_STONE_MANIFEST")
archive_file="${AVOCADO_STONE_BUILD_DIR}/${archive_name}"
archive_image="${archive_file%%.*}.img"
build_type=$(jq -r '.storage_devices.rootdisk.build_args.type // "fwup"' "$AVOCADO_STONE_MANIFEST")

# Check if AVOCADO_PROVISION_OUT is set and create directory
if [ -n "${AVOCADO_PROVISION_OUT:-}" ]; then
    echo "AVOCADO_PROVISION_OUT is set: $AVOCADO_PROVISION_OUT"
    mkdir -p "$AVOCADO_PROVISION_OUT"
fi

if [[ "$build_type" == "archive" ]]; then
    # Tryboot path: extract archive and create disk image with native tools
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    source "${SCRIPT_DIR}/stone-tryboot-common.sh"

    rm -f "${archive_image}"
    extract_archive "$archive_file" "$AVOCADO_STONE_BUILD_DIR"
    create_tryboot_disk_image "$AVOCADO_STONE_MANIFEST" "$AVOCADO_STONE_BUILD_DIR" "$archive_image"
else
    # Legacy fwup path
    fwup \
      -a \
      -i "${archive_file}" \
      -d "${archive_image}" \
      -t complete
fi

# Copy to AVOCADO_PROVISION_OUT if set
if [ -n "${AVOCADO_PROVISION_OUT:-}" ]; then
    echo "Copying output image to $AVOCADO_PROVISION_OUT"
    cp -v "${archive_image}" "$AVOCADO_PROVISION_OUT/"
    echo "Copy complete"
fi
