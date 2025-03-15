#!/bin/bash
# Simplified TPM start script for use with kas
# Usage: ./start-tpm.sh 
# Assumes pwd is the build directory

# Create a TPM state directory under the build
TPM_DIR="$(pwd)/tmp/tpm-state"
mkdir -p "$TPM_DIR"
TPM_SOCK="$TPM_DIR/swtpm-sock"

# Save socket location for other scripts
echo "$TPM_SOCK" > "$TPM_DIR/socket-path"

# Remove existing socket if it exists
if [ -S "$TPM_SOCK" ]; then
    rm -f "$TPM_SOCK"
fi

# Set the paths based on our successful debug run - using hardcoded paths
# that are known to work in your environment
SWTPM_BIN="$(pwd)/tmp/sysroots-components/x86_64/swtpm-native/usr/bin/swtpm"
if [ -z "$SWTPM_BIN" ]; then
    echo "Error: Could not find swtpm binary"
    return -1
fi

# Find the directory with the necessary libraries
LIB_SWTPM="(pwd)/tmp/sysroots-components/x86_64/swtpm-native/usr/lib/swtpm/libswtpm_libtpms.so.0"
if [ -z "$LIB_SWTPM" ]; then
    echo "Could not find libswtpm_libtpms.so.0"
    return -1
else
    # Get lib path from found library
    LIB_DIR=$(dirname "$LIB_SWTPM")
    PARENT_DIR=$(dirname "$LIB_DIR")
    LIB_PATH="$LIB_DIR:$PARENT_DIR"
fi

echo "Starting swtpm with socket at $TPM_SOCK"
LD_LIBRARY_PATH="$LIB_PATH" "$SWTPM_BIN" socket \
    --tpmstate dir="$TPM_DIR" \
    --ctrl type=unixio,path="$TPM_SOCK" \
    --log level=20 \
    --tpm2
