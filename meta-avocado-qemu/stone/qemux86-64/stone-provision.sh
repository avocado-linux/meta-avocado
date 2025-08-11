#!/usr/bin/env bash

# Environment variables provided by avocado:
# AVOCADO_STONE_MANIFEST - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR - stone data directory

archive_name=$(cat $AVOCADO_STONE_MANIFEST | jq -r .storage_devices.rootdisk.out)
archive_file="${AVOCADO_STONE_BUILD_DIR}/${archive_name}"
archive_image="${archive_file%%.*}.img"

fwup \
  -a \
  -i "${archive_file}" \
  -d "${archive_image}" \
  -t complete
