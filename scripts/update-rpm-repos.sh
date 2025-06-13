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

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "Step 1: Copying RPM files..."
"${SCRIPT_DIR}/copy-rpm-files.sh" "${SOURCE_DEPLOY_DIR}" "${TARGET_DEPLOY_DIR}"

echo "Step 2: Updating repository metadata..."
"${SCRIPT_DIR}/update-repo-metadata.sh" "${SOURCE_DEPLOY_DIR}" "${TARGET_DEPLOY_DIR}"

echo "Repository setup complete!" 
