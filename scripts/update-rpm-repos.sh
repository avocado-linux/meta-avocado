#!/bin/bash

set -e # Exit immediately if a command exits with a non-zero status.

# Main script
if [ $# -ne 2 ]; then
    echo "Usage: $0 <source-deploy-directory> <target-deploy-directory>"
    echo "Example: $0 /path/to/build/tmp/deploy/rpm /path/to/target/repo"
    exit 1
fi

SOURCE_DEPLOY_DIR=$1
TARGET_DEPLOY_DIR=$2
MAP_FILE="${SOURCE_DEPLOY_DIR}/avocado-repo.map"

if [ ! -f "${MAP_FILE}" ]; then
    echo "Error: Map file not found at ${MAP_FILE}" >&2
    exit 1
fi

echo "Using map file: ${MAP_FILE}"
echo "Source deploy directory: ${SOURCE_DEPLOY_DIR}"
echo "Target deploy directory: ${TARGET_DEPLOY_DIR}"

# Process mappings from the map file
while IFS='=' read -r key value || [ -n "$key" ]; do
    # Skip empty lines or lines without an equals sign
    if [ -z "$key" ] || [ -z "$value" ]; then
        echo "Skipping invalid line: $key=$value"
        continue
    fi

    source_dir="${SOURCE_DEPLOY_DIR}/${key}"
    # Target dir uses the full path specified in the map value
    target_dir="${TARGET_DEPLOY_DIR}/${value}"

    echo "Processing mapping: Source [${source_dir}] -> Target [${target_dir}]"

    if [ ! -d "${source_dir}" ]; then
        echo "Warning: Source directory ${source_dir} not found for key '${key}'. Skipping." >&2
        continue
    fi

    # Create target directory structure
    mkdir -p "${target_dir}"

    # Copy RPMs from source to target
    echo "Copying files from ${source_dir} to ${target_dir}"
    cp -a "${source_dir}"/* "${target_dir}/"

    # Create repository metadata
    echo "Creating repository metadata in ${target_dir}"
    if [ -d "${target_dir}/repodata" ]; then
        echo "Updating existing repository in ${target_dir}"
        createrepo_c --update "${target_dir}"
    else
        echo "Creating new repository in ${target_dir}"
        createrepo_c "${target_dir}"
    fi

done < "${MAP_FILE}"

echo "Repository setup complete based on map file!" 
