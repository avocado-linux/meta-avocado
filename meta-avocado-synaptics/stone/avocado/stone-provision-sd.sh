#!/usr/bin/env bash

# Environment variables provided by avocado:
# AVOCADO_STONE_MANIFEST - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR - stone data directory
# AVOCADO_DEVICE_CERT - device certificate content (base64 encoded pem)
# AVOCADO_DEVICE_KEY - device private key content (base64 encoded pem)
# AVOCADO_DEVICE_ID - device ID

archive_name=$(cat "$AVOCADO_STONE_MANIFEST" | jq -r .storage_devices.rootdisk.out)
archive_file="${AVOCADO_STONE_BUILD_DIR}/${archive_name}"
# Unused here: the sd profile lets fwup pick the destination device, while the
# sibling stone-provision-img.sh passes this path to `fwup -d`. Kept so the two
# scripts stay line-for-line comparable.
# shellcheck disable=SC2034
archive_image="${archive_file%%.*}.img"

fwup \
  -a \
  -i "${archive_file}" \
  -t complete
