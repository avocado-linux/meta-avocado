#!/usr/bin/env bash
#
# Provisioning for alif-e8-devkit: produce the SD card disk image only
# (no flashing). Used when the user wants to write the SD card on a host
# that isn't the SDK container, or just inspect the assembled image.

set -e
set -u
set -o pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DISK_IMAGE=$("${SCRIPT_DIR}/build-disk-image.sh")

if [ -n "${AVOCADO_PROVISION_OUT:-}" ]; then
    mkdir -p "$AVOCADO_PROVISION_OUT"
    cp -v "$DISK_IMAGE" "$AVOCADO_PROVISION_OUT/"
fi

cat <<EOF

alif-e8-devkit SD card image built:
  $DISK_IMAGE

To flash to an SD card, use \`avocado provision alif-e8-devkit --profile sd\`
or copy the .img off-host and write it with your imager of choice.
Note: the OSPI flash (TF-A + xipImage + DTB) must be programmed separately
via \`avocado provision alif-e8-devkit --profile serial\`.
EOF
