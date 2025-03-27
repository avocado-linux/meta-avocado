#!/bin/bash
# init-build.sh: Initialize the build directory for a kas-based project.
#
# Usage: ./init-build.sh /path/to/kas/machine.yml [build_dir]
#
# If build_dir is not provided, it defaults to "build-<basename>",
# where <basename> is the name of the kas/machine.yml file without its .yml extension.
#
# This script assumes that it resides in the meta-avocado repository root.
# It creates the build directory if needed, cd's into it, and then creates a relative symlink
# named "meta-avocado" that points back to the repository.

set -e

# Ensure the kas/machine.yml file is provided
if [ -z "$1" ]; then
    echo "Usage: $0 /path/to/kas/machine.yml [build_dir]"
    exit 1
fi

KAS_MACHINE_FILE="$1"
KAS_MACHINE_FILE_ABS="$(realpath "$KAS_MACHINE_FILE")"

if [ ! -f "$KAS_MACHINE_FILE" ]; then
    echo "Error: File '$KAS_MACHINE_FILE' does not exist."
    exit 1
fi

# Determine default build directory if not provided
if [ -z "$2" ]; then
    BASENAME=$(basename "$KAS_MACHINE_FILE" .yml)
    BUILD_DIR="build-${BASENAME}"
else
    BUILD_DIR="$2"
fi

# Determine the repository directory.
# This script is assumed to live in the meta-avocado repository root.
REPO_DIR="$(cd "$(dirname "$0")/../" && pwd)"

# Create the build directory if it doesn't exist
mkdir -p "$BUILD_DIR" || { echo "Error: Could not create directory $BUILD_DIR"; exit 1; }

# Change into the build directory
cd "$BUILD_DIR" || { echo "Error: Could not change directory to $BUILD_DIR"; exit 1; }

# Create a relative symlink to meta-avocado (the repository root) if it doesn't already exist.
if [ ! -e "meta-avocado" ]; then
    # Compute the relative path from the build directory to the repository directory.
    REL_PATH=$(realpath --relative-to="$PWD" "$REPO_DIR")
    ln -s "$REL_PATH" meta-avocado
    echo "Created symlink 'meta-avocado' -> $REL_PATH"
else
    echo "Symlink 'meta-avocado' already exists"
fi
# Convert the kas machine file to an absolute path
KAS_MACHINE_FILE_REL="$(realpath --relative-to="$PWD" "$KAS_MACHINE_FILE_ABS")"
# Create an .envrc file with KAS_YML pointing to the absolute path of the kas machine file.
cat <<EOF > .envrc
export KAS_YML="$KAS_MACHINE_FILE_REL"
EOF
echo "Created .envrc file with KAS_YML set to $KAS_MACHINE_FILE_REL"

echo "Build initialization complete in $(pwd)."
