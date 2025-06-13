#!/bin/bash

set -e # Exit immediately if a command exits with a non-zero status.

# Main script
if [ $# -ne 1 ]; then
    echo "Usage: $0 <target-repo-base-directory>"
    echo "Example: $0 /path/to/repos"
    exit 1
fi

TARGET_REPO_BASE_DIR=$1

if [ ! -d "${TARGET_REPO_BASE_DIR}" ]; then
    echo "Error: Base repository directory not found at ${TARGET_REPO_BASE_DIR}" >&2
    exit 1
fi

echo "Starting cleanup of repositories in ${TARGET_REPO_BASE_DIR}"

# Iterate over each subdirectory in the target base directory
# These subdirectories are assumed to be individual repositories
for repo_dir in "${TARGET_REPO_BASE_DIR}"/*/; do
    if [ -d "${repo_dir}" ]; then
        repo_name=$(basename "${repo_dir}")
        echo "Processing repository: ${repo_name} at ${repo_dir}"

        # Find .rpm files older than 7 days in the current repository directory (not in subdirectories)
        # The -delete action implies -depth. Using -maxdepth 1 to be explicit.
        # Capture the list of files to be deleted
        files_to_delete=$(find "${repo_dir}" -maxdepth 1 -name "*.rpm" -mtime +7 -print)

        if [ -n "${files_to_delete}" ]; then
            echo "Found old packages in ${repo_dir}:"
            # Print and then delete
            find "${repo_dir}" -maxdepth 1 -name "*.rpm" -mtime +7 -print -delete
            
            echo "Updating repository metadata for ${repo_dir}"
            # Check if repodata exists, as --update requires it.
            # If not, it means the repo might be empty after deletion, or was malformed.
            # createrepo_c will create it if it's missing and there are RPMs.
            if [ -d "${repo_dir}/repodata" ] || [ -n "$(ls -A ${repo_dir}/*.rpm 2>/dev/null)" ]; then
                 createrepo_c --update "${repo_dir}"
            else
                echo "Skipping metadata update for ${repo_dir} as it's empty or has no repodata."
            fi
        else
            echo "No old packages found in ${repo_dir}."
        fi
    fi
done

echo "Repository cleanup complete!" 
