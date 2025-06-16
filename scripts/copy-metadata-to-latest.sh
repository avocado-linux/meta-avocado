#!/bin/bash

set -e # Exit immediately if a command exits with a non-zero status.

# Simple script to copy repository metadata from releases to latest directory
# S3 sync will handle the atomic update by uploading supporting files first, then repomd.xml

if [ $# -ne 2 ]; then
    echo "Usage: $0 <releases-directory> <latest-directory>"
    echo "Example: $0 /path/to/releases/apollo/edge/date /path/to/latest/apollo/edge"
    echo ""
    echo "This script copies repository metadata from releases to latest directory."
    echo "The S3 sync process will handle atomic updates."
    exit 1
fi

RELEASES_DIR="$1"
LATEST_DIR="$2"

if [ ! -d "$RELEASES_DIR" ]; then
    echo "Error: Releases directory $RELEASES_DIR not found" >&2
    exit 1
fi

echo "Releases directory: $RELEASES_DIR"
echo "Latest directory: $LATEST_DIR"
echo ""

# Create latest directory if it doesn't exist
mkdir -p "$LATEST_DIR"

# Copy all repodata directories from releases to latest
echo "Copying repository metadata from releases to latest..."
find "$RELEASES_DIR" -type d -name "repodata" | while read -r source_repodata_dir; do
    # Calculate the relative path from releases directory
    repo_relative_path="${source_repodata_dir#${RELEASES_DIR}/}"

    # Calculate target path in latest directory
    target_repodata_dir="${LATEST_DIR}/${repo_relative_path}"

    echo "Copying: $repo_relative_path"

    # Create target directory and copy contents
    mkdir -p "$target_repodata_dir"
    cp -r "$source_repodata_dir"/* "$target_repodata_dir/"
done

echo ""
echo "Repository metadata copy complete!"
echo "Latest directory now contains current repository metadata."
echo "S3 sync will handle atomic updates by uploading supporting files first, then repomd.xml files."
