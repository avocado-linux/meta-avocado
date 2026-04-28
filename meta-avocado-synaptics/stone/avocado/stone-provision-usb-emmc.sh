#!/usr/bin/env bash
set -euo pipefail

# Environment variables provided by avocado:
# AVOCADO_STONE_MANIFEST - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory (input artifacts)
# AVOCADO_STONE_DATA_DIR - stone data directory
#
# SDK environment variables (set by sourcing the SDK environment-setup script):
# OECORE_NATIVE_SYSROOT - path to the native SDK sysroot

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNAIMG_DIR="${AVOCADO_STONE_BUILD_DIR}/SYNAIMG"
USBBOOT_IMAGES="${OECORE_NATIVE_SYSROOT}/usr/share/astra-update/astra-usbboot-images"

# ---------------------------------------------------------------------------
# Verify required tools and paths
# ---------------------------------------------------------------------------
for tool in astra-update jq; do
    if ! command -v "${tool}" &>/dev/null; then
        echo "ERROR: required tool '${tool}' not found in PATH" >&2
        exit 1
    fi
done

if [ ! -d "${USBBOOT_IMAGES}" ]; then
    echo "ERROR: astra-usbboot-images not found at ${USBBOOT_IMAGES}" >&2
    echo "       Ensure nativesdk-astra-usbboot-images is installed in the SDK." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Build the SYNAIMG
# ---------------------------------------------------------------------------
echo "Building SYNAIMG..."
AVOCADO_PROVISION_OUT="${SYNAIMG_DIR}" \
    bash "${SCRIPT_DIR}/stone-provision-synaimg.sh"

# ---------------------------------------------------------------------------
# Provision the board via USB eMMC
# ---------------------------------------------------------------------------
echo "Provisioning board via USB eMMC (chip: sl1680)..."
astra-update -c sl1680 -B "${USBBOOT_IMAGES}/" -f "${SYNAIMG_DIR}/"

echo "USB eMMC provisioning complete."
