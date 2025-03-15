#!/bin/bash
# Script to run QEMU with TPM support via kas
# Usage: ./run-qemu-tpm.sh
# Assumes pwd is build directory

# TPM socket path from the stored location
TPM_DIR="$(pwd)/tmp/tpm-state"
TPM_SOCK_FILE="$TPM_DIR/socket-path"

if [ -f "$TPM_SOCK_FILE" ]; then
    TPM_SOCK=$(cat "$TPM_SOCK_FILE")
else
    # Fallback if socket path file not found
    TPM_SOCK="$TPM_DIR/swtpm-sock"
fi

# Check if TPM socket exists
if [ ! -S "$TPM_SOCK" ]; then
    echo "Error: TPM socket not found at $TPM_SOCK"
    echo "Please run start-tpm.sh first in another terminal"
    exit 1
fi

# Image paths relative to build directory
MACHINE="avocado-qemux86-64"
DEPLOY_DIR="$(pwd)/tmp/deploy/images/$MACHINE"
IMAGE_NAME="avocado-image-rootfs-$MACHINE.rootfs.wic"
OVMF_CODE="ovmf.code.qcow2"
OVMF_VARS="ovmf.vars.qcow2"
QEMU_EXEC="$(pwd)/tmp/sysroots-components/x86_64/qemu-system-native/usr/bin/qemu-system-x86_64"

echo "Starting QEMU with TPM support..."
echo "TPM socket: $TPM_SOCK"
echo "-------------------------------------"
echo "Add these kernel parameters to fix TPM self-test issues:"
echo "tpm_tis.force=1 tpm_tis.interrupts=0"
echo "-------------------------------------"

# Run QEMU with TPM support
$QEMU_EXEC \
  -drive file="$DEPLOY_DIR/$IMAGE_NAME",format=raw,if=virtio \
  -drive if=pflash,format=qcow2,readonly=on,file="$DEPLOY_DIR/$OVMF_CODE" \
  -drive if=pflash,format=qcow2,file="$DEPLOY_DIR/$OVMF_VARS" \
  -m 256 \
  -enable-kvm \
  -cpu host \
  -nographic \
  -chardev socket,id=chrtpm,path="$TPM_SOCK" \
  -tpmdev emulator,id=tpm0,chardev=chrtpm \
  -device tpm-tis,tpmdev=tpm0
