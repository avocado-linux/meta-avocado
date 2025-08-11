#!/usr/bin/env bash

set -e # Exit immediately if a command exits with a non-zero status.

# Main script
if [ $# -ne 1 ]; then
    echo "Usage: $0 <yocto-deploy-directory>"
    echo "Example: $0 /path/to/build/tmp/deploy/rpm"
    exit 1
fi

YOCTO_DEPLOY_DIR=$1
MAP_FILE="${YOCTO_DEPLOY_DIR}/avocado-repo.map"

releasever="${AVOCADO_SDK_REPO_RELEASE:-dev}"

if [ ! -f "${MAP_FILE}" ]; then
    echo "Error: Map file not found at ${MAP_FILE}" >&2
    exit 1
fi

echo "Using map file: ${MAP_FILE}"

# Process mappings from the map file
while IFS='=' read -r key value || [ -n "$key" ]; do
    # Skip empty lines or lines without an equals sign
    value=$(eval "echo \"${value}\"")

    if [ -z "$key" ] || [ -z "$value" ]; then
        echo "Skipping invalid line: $key=$value"
        continue
    fi

    value=$(eval "echo \"${value}\"")

    source_dir="${YOCTO_DEPLOY_DIR}/${key}"
    # Target dir uses the full path specified in the map value
    target_dir="/var/www/html/${value}"

    echo "Processing mapping: Source [${source_dir}] -> Target [${target_dir}]"

    if [ ! -d "${source_dir}" ]; then
        echo "Warning: Source directory ${source_dir} not found for key '${key}'. Skipping." >&2
        continue
    fi

    # Create target directory structure
    mkdir -p "${target_dir}"

    # Sync RPMs from source to target with deletion of extra files
    # Use rsync to ensure destination is an exact mirror of source
    echo "Syncing files from ${source_dir} to ${target_dir} (with deletion of extra files)"
    rsync -av --delete "${source_dir}/" "${target_dir}/"

    # Create repository metadata
    echo "Creating repository metadata in ${target_dir}"
    createrepo_c "${target_dir}"

done < "${MAP_FILE}"

echo "Repository setup complete based on map file!"
