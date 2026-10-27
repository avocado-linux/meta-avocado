#!/bin/sh
# shellcheck disable=SC2015  # ok() always succeeds, so "A && ok || bad" is an if/else here
# Host test for the NanoPi R5S disk image: build-disk-image.sh against the real
# stone manifest, with sgdisk/mkfs.fat/mtools replaced by stand-ins that record
# their arguments (the CI image has none of them), plus the U-Boot environment
# offsets that the manifest, U-Boot and fw_env.config must agree on.
# Run: sh meta-avocado-rockchip/stone/nanopi-r5s/tests/test-build-disk-image.sh
set -u
here=$(cd "$(dirname "$0")" && pwd)
layer=$(cd "$here/../../.." && pwd)
manifest="$layer/stone/stone-nanopi-r5s.json"
w=$(mktemp -d)
trap 'rm -rf "$w"' EXIT
fail=0
ok() { echo "ok - $1"; }
bad() { echo "FAIL - $1"; fail=1; }

mkdir -p "$w/bin" "$w/data" "$w/build"
for t in sgdisk mkfs.fat mmd mcopy; do
  printf '#!/bin/sh\necho "%s $*" >> "%s/calls"\n' "$t" "$w" >"$w/bin/$t"
  chmod +x "$w/bin/$t"
done
# Sparse stand-ins for every image the manifest names.
for key in $(jq -r '.storage_devices.rootdisk.images | to_entries[] | select(.value | type == "string") | .value' "$manifest") \
  $(jq -r '.storage_devices.rootdisk.images.boot.build_args.files[].in' "$manifest"); do
  truncate -s 1M "$w/data/$key"
done
truncate -s 245M "$w/data/$(jq -r '.storage_devices.rootdisk.images.var' "$manifest")"
truncate -s 128K "$w/data/uboot.env"   # mkenvimage -s 0x20000

out=$(PATH="$w/bin:$PATH" AVOCADO_STONE_MANIFEST="$manifest" AVOCADO_STONE_DATA_DIR="$w/data" \
  AVOCADO_STONE_BUILD_DIR="$w/build" bash "$layer/stone/nanopi-r5s/build-disk-image.sh" 2>&1)
[ -f "$w/build/avocado-os-avocado-nanopi-r5s.img" ] && ok "disk image built" || bad "no image: $out"

# Partition N spans exactly its manifest size: 128 MiB = 262144 sectors, so
# boot-a at 32 MiB (sector 65536) must end at 327679. "+262143" would be a
# length, one sector short, and a full-size boot image would not fit on OTA.
grep -q -- '-n 1:65536:327679 ' "$w/calls" && ok "boot-a spans 65536-327679 (128 MiB)" ||
  bad "boot-a extent: $(grep -o -- '-n 1:[^ ]*' "$w/calls")"
grep -q -- '-n 2:327680:589823 ' "$w/calls" && ok "boot-b spans 327680-589823 (128 MiB)" ||
  bad "boot-b extent: $(grep -o -- '-n 2:[^ ]*' "$w/calls")"

# No fixed partition GUIDs: two Avocado disks in one board (eMMC + microSD)
# must not share them, so sgdisk picks fresh ones on every provision and
# U-Boot names the booted disk's root by PARTUUID.
jq -e '[.storage_devices.rootdisk.partitions[] | select(has("partition_uuid"))] | length == 0' "$manifest" >/dev/null &&
  ok "the manifest pins no partition GUIDs" || bad "the manifest pins partition GUIDs"
grep -q -- ' -u ' "$w/calls" && bad "sgdisk is given fixed GUIDs: $(grep -o -- '-u [^ ]*' "$w/calls")" ||
  ok "sgdisk generates every partition GUID"

# The U-Boot environment: written at 16 MiB, where U-Boot and fw_env read it.
echo "$out" | grep -q 'writing uboot-env from uboot.env at sector 32768' && ok "uboot.env written at 16 MiB" ||
  bad "uboot-env placement: $(echo "$out" | grep uboot-env)"
cfg="$layer/recipes-bsp/u-boot/u-boot/avocado-env-mmc.cfg"
grep -q '^CONFIG_ENV_OFFSET=0x1000000$' "$cfg" && grep -q '^CONFIG_ENV_OFFSET_REDUND=0x1040000$' "$cfg" &&
  ok "U-Boot reads its env at 0x1000000/0x1040000" || bad "U-Boot env offsets in $cfg"
for f in recipes-bsp/u-boot/avocado-uboot-env/avocado-uboot-env recipes-bsp/u-boot/libubootenv/fw_env.config; do
  grep -q '0x1000000' "$layer/$f" && grep -q '0x1040000' "$layer/$f" && ok "$f uses the same offsets" || bad "$f offsets"
done

# Provision scripts run from the bundle: everything they call must be shipped.
jq -e '.provision.files | index("build-disk-image.sh")' "$manifest" >/dev/null &&
  ok "provision.files ships build-disk-image.sh" || bad "build-disk-image.sh missing from provision.files"
for s in $(jq -r '.provision.profiles[].script' "$manifest"); do
  [ -f "$layer/stone/nanopi-r5s/$s" ] && ok "profile script $s exists" || bad "profile script $s missing"
done

exit $fail
