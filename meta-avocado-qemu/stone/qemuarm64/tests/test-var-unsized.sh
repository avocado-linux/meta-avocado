#!/usr/bin/env bash
# The var partition must carry no size in the qemuarm64 manifest.
#
# avocado-provision-qemuarm64 sizes var from the built image
# (`stone provision --partition-size var=<bytes>`), but a size in the manifest
# wins over that, and rootdisk.conf then asserts the image fits it: a var image
# larger than the pinned size fails provisioning with a fwup size assertion.
# Every other BSP manifest leaves var unsized for the same reason.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
manifest=${1:-$here/../../stone-qemuarm64.json}

var=$(jq -c '.storage_devices.rootdisk.partitions[] | select(.name == "var")' "$manifest")
if [ -z "$var" ]; then
  echo "  FAIL - no var partition in $manifest"
  exit 1
fi
if [ "$(jq -r '.expand' <<<"$var")" != "true" ]; then
  echo "  FAIL - var is not the expand partition: $var"
  exit 1
fi
if jq -e 'has("size") or has("size_unit")' <<<"$var" >/dev/null; then
  echo "  FAIL - var pins a size; the provision hook's --partition-size cannot apply: $var"
  exit 1
fi
echo "  ok   - var is unsized and expands"
