#!/usr/bin/env bash

set -e # Exit immediately if a command exits with a non-zero status.

# Force line-buffered stdout so progress is visible in container logs
if command -v stdbuf &>/dev/null && [ -z "$_STAGE_RPMS_UNBUFFERED" ]; then
    export _STAGE_RPMS_UNBUFFERED=1
    exec stdbuf -oL "$0" "$@"
fi

# Main script
METADATA_ONLY=0
if [ "${1:-}" = "--metadata-only" ]; then
    METADATA_ONLY=1
    shift
fi

if [ $# -ne 3 ]; then
    echo "Usage: $0 [--metadata-only] <source-deploy-directory> <target-deploy-directory> <releasever>"
    echo "Example: $0 /path/to/build/tmp/deploy/rpm /path/to/target/repo latest/apollo/edge"
    echo ""
    echo "  --metadata-only  Validate the map and per-entry source dirs, but skip"
    echo "                   the bulk tar-pipe of RPMs. Use when RPMs are uploaded"
    echo "                   directly from the build (avocado-pulp-upload bbclass)."
    exit 1
fi

SOURCE_DEPLOY_DIR=$1
TARGET_DEPLOY_DIR=$2
releasever=$3

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
    value=$(eval "echo \"${value}\"")

    # Skip empty lines or lines without an equals sign
    if [ -z "$key" ] || [ -z "$value" ]; then
        echo "Skipping invalid line: $key=$value"
        continue
    fi

    # `repo=<root>` lines describe repository roots for the metadata/targets.json
    # steps, not package source dirs — staging ignores them.
    if [ "$key" = "repo" ]; then
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

    if [ "${METADATA_ONLY}" = "1" ]; then
        file_count=$(find "${source_dir}" -type f | wc -l)
        echo "Metadata-only: skipping tar-pipe of ${file_count} files from ${source_dir}"
        continue
    fi

    # Create target directory structure
    mkdir -p "${target_dir}"

    # Stream files via tar pipe — avoids per-file NFS round-trips
    file_count=$(find "${source_dir}" -type f | wc -l)
    echo "Staging ${file_count} files from ${source_dir} to ${target_dir}"
    tar cf - -C "${source_dir}" . | tar xf - -C "${target_dir}"
    echo "Done: ${source_dir} -> ${target_dir}"

done < "${MAP_FILE}"

echo "RPM file syncing complete!"
