#!/bin/bash

set -e # Exit immediately if a command exits with a non-zero status.

# Function to find leaf directories containing RPMs
find_rpm_dirs() {
    local dir="$1"
    find "$dir" -type d -not -path "*/repodata/*" | while read -r subdir; do
        # Check if this directory contains RPMs
        if [ -n "$(find "$subdir" -maxdepth 1 -name "*.rpm" -print -quit)" ]; then
            # Check if this is a leaf directory (no subdirectories with RPMs)
            if [ -z "$(find "$subdir" -mindepth 1 -type d -not -path "*/repodata/*" -exec sh -c '[ -n "$(find \"$0\" -maxdepth 1 -name \"*.rpm\" -print -quit)" ]' {} \; -print -quit)" ]; then
                echo "$subdir"
            fi
        fi
    done
}

# Main script
if [ $# -ne 1 ]; then
    echo "Usage: $0 <target-deploy-directory>"
    echo "Example: $0 /path/to/target/repo"
    exit 1
fi

TARGET_DEPLOY_DIR="$1"

if [ ! -d "${TARGET_DEPLOY_DIR}" ]; then
    echo "Error: Target directory ${TARGET_DEPLOY_DIR} not found" >&2
    exit 1
fi

echo "Target deploy directory: ${TARGET_DEPLOY_DIR}"

# Find and process all leaf directories containing RPMs
while IFS= read -r rpm_dir; do
    echo "Processing repository: ${rpm_dir}"
    
    if [ -d "${rpm_dir}/repodata" ]; then
        echo "Updating existing repository in ${rpm_dir}"
        createrepo_c --update "${rpm_dir}"
    else
        echo "Creating new repository in ${rpm_dir}"
        createrepo_c "${rpm_dir}"
    fi
done < <(find_rpm_dirs "${TARGET_DEPLOY_DIR}")

echo "Repository metadata update complete!" 
