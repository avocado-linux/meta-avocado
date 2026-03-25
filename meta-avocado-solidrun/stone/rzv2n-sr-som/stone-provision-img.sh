#!/usr/bin/env bash

# Environment variables provided by avocado:
# AVOCADO_STONE_MANIFEST - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR - stone data directory
# AVOCADO_DEVICE_CERT - device certificate content (base64 encoded pem)
# AVOCADO_DEVICE_KEY - device private key content (base64 encoded pem)
# AVOCADO_DEVICE_ID - device ID

archive_name=$(cat $AVOCADO_STONE_MANIFEST | jq -r .storage_devices.rootdisk.out)
archive_file="${AVOCADO_STONE_BUILD_DIR}/${archive_name}"
archive_image="${archive_file%%.*}.img"

# Check if AVOCADO_PROVISION_OUT is set and create directory
if [ -n "${AVOCADO_PROVISION_OUT:-}" ]; then
    echo "AVOCADO_PROVISION_OUT is set: $AVOCADO_PROVISION_OUT"
    mkdir -p "$AVOCADO_PROVISION_OUT"
fi

fwup \
  -a \
  -i "${archive_file}" \
  -d "${archive_image}" \
  -t complete

# Copy to AVOCADO_PROVISION_OUT if set
if [ -n "${AVOCADO_PROVISION_OUT:-}" ]; then
    echo "Copying output image to $AVOCADO_PROVISION_OUT"
    cp -v "${archive_image}" "$AVOCADO_PROVISION_OUT/"
    echo "Copy complete"
fi
