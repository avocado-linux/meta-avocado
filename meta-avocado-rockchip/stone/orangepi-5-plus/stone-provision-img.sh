#!/usr/bin/env bash
#
# img profile for orangepi-5-plus: build the GPT disk image and (optionally)
# copy it to AVOCADO_PROVISION_OUT for the user to flash with their preferred
# tool. No on-host writing happens here -- use the sd profile for that.

set -e
set -u
set -o pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DISK_IMAGE=$("${SCRIPT_DIR}/build-disk-image.sh")

if [ -n "${AVOCADO_PROVISION_OUT:-}" ]; then
    mkdir -p "$AVOCADO_PROVISION_OUT"
    cp -v "$DISK_IMAGE" "$AVOCADO_PROVISION_OUT/"
fi

echo
echo "Disk image built: $DISK_IMAGE"
