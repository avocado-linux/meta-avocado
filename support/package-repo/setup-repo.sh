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

# Two passes over the map:
#   1. `arch_dir=<pkg_path>` lines -> rsync packages into place (no per-arch repomd).
#   2. `repo=<root>` lines         -> createrepo_c ONCE per repo root, recursing into
#      any arch subdirs (W1: one `[<machine>-target]` repo @ target/<machine>).
# Metadata lives only at the declared repo roots, matching the production per-machine
# layout (the avocado-cli target repo is target/<machine>, not target/<machine>/<arch>).

# Pass 1: stage packages.
while IFS='=' read -r key value || [ -n "$key" ]; do
    value=$(eval "echo \"${value}\"")

    if [ -z "$key" ] || [ -z "$value" ]; then
        echo "Skipping invalid line: $key=$value"
        continue
    fi

    # repo= lines are repo roots, handled in pass 2.
    if [ "$key" = "repo" ]; then
        continue
    fi

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
done < "${MAP_FILE}"

# Pass 2: one repomd per repo root (recurses into arch subdirs).
while IFS='=' read -r key value || [ -n "$key" ]; do
    [ "$key" = "repo" ] || continue
    value=$(eval "echo \"${value}\"")
    [ -n "$value" ] || continue

    repo_dir="/var/www/html/${value}"
    if [ ! -d "${repo_dir}" ]; then
        echo "Warning: repo root ${repo_dir} not found, skipping." >&2
        continue
    fi

    echo "Creating repository metadata in ${repo_dir} (covering arch subdirs)"
    createrepo_c "${repo_dir}"
done < "${MAP_FILE}"

echo "Repository setup complete based on map file!"
