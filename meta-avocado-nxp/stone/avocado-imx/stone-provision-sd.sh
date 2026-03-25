#!/usr/bin/env bash

# Environment variables provided by avocado:
# AVOCADO_STONE_MANIFEST - path to manifest JSON file
# AVOCADO_STONE_BUILD_DIR - build output directory
# AVOCADO_STONE_DATA_DIR - stone data directory
# AVOCADO_DEVICE_CERT - device certificate content (base64 encoded pem)
# AVOCADO_DEVICE_KEY - device private key content (base64 encoded pem)
# AVOCADO_DEVICE_ID - device ID

archive_name=$(cat $AVOCADO_STONE_MANIFEST | jq -r .storage_devices.rootdisk.out)
archive_file="${AVOCADO_STONE_BUILD_DIR}/${archive_name}"
archive_image="${archive_file%%.*}.img"

# When USB passthrough is unavailable (Docker Desktop on macOS/Windows),
# produce a disk image for host-side burning instead of flashing directly.
if [ "${AVOCADO_USB_PASSTHROUGH:-1}" = "0" ]; then
    echo "=========================================="
    echo "Docker Desktop detected - no device access"
    echo "Producing disk image for host-side burning"
    echo "=========================================="

    if [ -z "${AVOCADO_PROVISION_OUT:-}" ]; then
        echo "Error: AVOCADO_PROVISION_OUT must be set when USB passthrough is unavailable"
        exit 1
    fi

    mkdir -p "$AVOCADO_PROVISION_OUT"

    echo "Creating raw disk image from archive..."
    fwup -a -i "${archive_file}" -d "${archive_image}" -t complete

    echo "Copying image to provision output..."
    cp -v "${archive_image}" "$AVOCADO_PROVISION_OUT/"

    # Write result metadata for CLI host-side burning
    cat > "$AVOCADO_PROVISION_OUT/.provision-result.json" <<RESULT_EOF
{
  "host_action": "burn_removable",
  "image": "$(basename "${archive_image}")"
}
RESULT_EOF

    echo "Disk image ready for host-side SD card burning."
    exit 0
fi

fwup \
  -a \
  -i "${archive_file}" \
  -t complete
