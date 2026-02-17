#!/usr/bin/env bash

# PXE Boot Provisioning Script for Intel x86-64
#
# Prepares PXE boot artifacts for network provisioning. The output directory
# contains everything needed to boot a target system over the network and
# install Avocado OS to its local disk.
#
# Environment variables provided by avocado/stone:
# AVOCADO_STONE_MANIFEST  - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR  - stone data directory
# AVOCADO_PROVISION_OUT   - (optional) output directory for PXE artifacts

set -e
set -u
set -o pipefail

MANIFEST="$AVOCADO_STONE_MANIFEST"
DATA_DIR="$AVOCADO_STONE_DATA_DIR"
BUILD_DIR="$AVOCADO_STONE_BUILD_DIR"

# Read image filenames from manifest
ROOTFS_IMAGE=$(jq -r '.storage_devices.rootdisk.images.rootfs' "$MANIFEST")
VAR_IMAGE=$(jq -r '.storage_devices.rootdisk.images.var' "$MANIFEST")
INITRAMFS_IMAGE=$(jq -r '.storage_devices.rootdisk.images.initramfs' "$MANIFEST")
KERNEL_IMAGE=$(jq -r '.storage_devices.rootdisk.images.kernel' "$MANIFEST")
BOOTLOADER_IMAGE=$(jq -r '.storage_devices.rootdisk.images.bootloader' "$MANIFEST")
PLATFORM=$(jq -r '.runtime.platform' "$MANIFEST")

# Determine output directory
PXE_OUT="${AVOCADO_PROVISION_OUT:-${BUILD_DIR}/pxe}"
mkdir -p "$PXE_OUT"

echo "=== Preparing PXE boot artifacts for ${PLATFORM} ==="
echo "  Data directory: ${DATA_DIR}"
echo "  Output directory: ${PXE_OUT}"

# =============================================================================
# Copy boot artifacts for TFTP serving
# =============================================================================
echo ""
echo "--- Boot artifacts (TFTP) ---"

# Kernel
if [ -f "${DATA_DIR}/${KERNEL_IMAGE}" ]; then
    cp -v "${DATA_DIR}/${KERNEL_IMAGE}" "${PXE_OUT}/bzImage"
else
    echo "ERROR: Kernel not found: ${DATA_DIR}/${KERNEL_IMAGE}"
    exit 1
fi

# Initramfs
if [ -f "${DATA_DIR}/${INITRAMFS_IMAGE}" ]; then
    cp -v "${DATA_DIR}/${INITRAMFS_IMAGE}" "${PXE_OUT}/initramfs.cpio.zst"
else
    echo "ERROR: Initramfs not found: ${DATA_DIR}/${INITRAMFS_IMAGE}"
    exit 1
fi

# =============================================================================
# Copy system images for HTTP/NFS serving (used by initramfs installer)
# =============================================================================
echo ""
echo "--- System images (HTTP/NFS) ---"

# EFI bootloader
if [ -f "${DATA_DIR}/${BOOTLOADER_IMAGE}" ]; then
    cp -v "${DATA_DIR}/${BOOTLOADER_IMAGE}" "${PXE_OUT}/"
fi

# Rootfs
if [ -f "${DATA_DIR}/${ROOTFS_IMAGE}" ]; then
    cp -v "${DATA_DIR}/${ROOTFS_IMAGE}" "${PXE_OUT}/"
fi

# Var
if [ -f "${DATA_DIR}/${VAR_IMAGE}" ]; then
    cp -v "${DATA_DIR}/${VAR_IMAGE}" "${PXE_OUT}/"
fi

# =============================================================================
# Generate iPXE boot script
# =============================================================================
echo ""
echo "--- Generating iPXE boot script ---"

cat > "${PXE_OUT}/boot.ipxe" <<'IPXE'
#!ipxe
# Avocado OS PXE Boot Script
# Serve this file from your HTTP server and chainload from iPXE

# Set the base URL to your HTTP server hosting these files
# Adjust this to match your network setup
set base-url http://${next-server}/avocado

kernel ${base-url}/bzImage initrd=initramfs.cpio.zst avocado.install=1 avocado.install.url=${base-url} console=tty0 console=ttyS0,115200n8
initrd ${base-url}/initramfs.cpio.zst
boot
IPXE

echo "  Created boot.ipxe"

# =============================================================================
# Generate PXELINUX config (legacy BIOS PXE fallback)
# =============================================================================
mkdir -p "${PXE_OUT}/pxelinux.cfg"

cat > "${PXE_OUT}/pxelinux.cfg/default" <<PXECFG
DEFAULT avocado
PROMPT 0
TIMEOUT 50

LABEL avocado
    KERNEL bzImage
    INITRD initramfs.cpio.zst
    APPEND avocado.install=1 console=tty0 console=ttyS0,115200n8
PXECFG

echo "  Created pxelinux.cfg/default"

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "=== PXE boot artifacts prepared ==="
echo ""
echo "Directory contents:"
ls -lh "$PXE_OUT"
echo ""
echo "To use these artifacts:"
echo ""
echo "  iPXE (UEFI):"
echo "    1. Host all files via HTTP server"
echo "    2. Chainload boot.ipxe from your DHCP/iPXE config"
echo ""
echo "  PXELINUX (Legacy BIOS):"
echo "    1. Copy bzImage and initramfs.cpio.zst to TFTP root"
echo "    2. Copy pxelinux.cfg/default to TFTP pxelinux.cfg/"
echo ""
echo "  The initramfs installer will download rootfs and var images"
echo "  from the HTTP server to install Avocado OS to the target disk."
