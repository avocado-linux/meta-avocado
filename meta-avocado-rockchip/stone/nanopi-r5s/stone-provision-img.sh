#!/usr/bin/env bash

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
