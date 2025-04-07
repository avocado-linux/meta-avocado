#!/bin/bash

# Function to create repository for a specific directory
create_repo() {
    local repo_name=$1
    local source_dir=$2
    local target_dir="/var/www/html/${repo_name}"
    
    # Create target directory
    mkdir -p "${target_dir}"
    
    # Copy RPMs from source to target
    if [ -d "${source_dir}" ]; then
        cp -r "${source_dir}"/* "${target_dir}/"
    fi
    
    # Create repository metadata
    createrepo_c "${target_dir}"
}

# Main script
if [ $# -ne 1 ]; then
    echo "Usage: $0 <yocto-deploy-directory>"
    echo "Example: $0 /path/to/build/tmp/deploy/rpm"
    exit 1
fi

YOCTO_DEPLOY_DIR=$1

# Process each directory under the deploy/rpm directory
for dir in "${YOCTO_DEPLOY_DIR}"/*; do
    if [ -d "${dir}" ]; then
        repo_name=$(basename "${dir}")
        echo "Processing repository: ${repo_name}"
        create_repo "${repo_name}" "${dir}"
    fi
done

echo "Repository setup complete!" 
