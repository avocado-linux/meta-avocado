#!/usr/bin/env bash

# Standalone test for the NXP device-tree overlay delivery hook. Runs the real
# hook against a ucm-imx8m-plus-shaped stone manifest and checks what it writes:
# the stone fragment (which files reach the boot FAT, and where), the
# avocado-overlays.txt the U-Boot env imports, and the claims in the manifest.
# Runs on any host with python3 and jq. Not packaged into the recipe.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
hook="$here/../files/device-tree-overlay-deliver"

pass=0
fail=0
ok() {
  printf '  ok   - %s\n' "$1"
  pass=$((pass + 1))
}
bad() {
  printf '  FAIL - %s\n' "$1"
  fail=$((fail + 1))
}

for t in python3 jq; do
  command -v "$t" >/dev/null 2>&1 || {
    echo "SKIP: host missing $t"
    exit 0
  }
done

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

loose_stone='{
  "runtime": {"platform": "avocado-ucm-imx8m-plus"},
  "storage_devices": {"rootdisk": {"images": {
    "imx_boot": "imx-boot",
    "boot": {"out": "boot.img", "build_args": {"type": "fat", "files": [
      "avocado-image-initramfs.cpio.zst", "Image", "ucm-imx8m-plus.dtb",
      "iot-gate-imx8plus.dtb", "ucm-imx8m-plus-can.dtbo"]}},
    "rootfs": "rootfs.erofs"}}}}'
fit_stone='{
  "runtime": {"platform": "avocado-imx8mp-evk"},
  "storage_devices": {"rootdisk": {"images": {
    "boot": {"out": "boot.img", "build_args": {"type": "fat", "files": ["fitImage"]}}}}}}'

ov() { # name stock
  printf '{"name":"%s","file":"%s.dtbo","params":{},"stock":%s,"claimed_by":null}' "$1" "$1" "$2"
}

# run <case> <stone> <overlays json array> <boot_config json array>
run() {
  local d="$work/$1"
  mkdir -p "$d"
  printf '%s' "$2" >"$d/stone.json"
  printf '{"version":1,"overlays":%s,"boot_config":%s,"boot_config_claimed_by":null}' "$3" "$4" \
    >"$d/overlays.manifest.json"
  AVOCADO_DTBO_STAGING="$d" \
    AVOCADO_OVERLAYS_MANIFEST="$d/overlays.manifest.json" \
    AVOCADO_DELIVERY_FRAGMENT="$d/fragment.json" \
    AVOCADO_STONE_MANIFEST="$d/stone.json" \
    "$hook" >/dev/null 2>"$d/err"
}

appends() { jq -c '.storage_devices.rootdisk.images.boot.build_args.files_append' "$work/$1/fragment.json"; }

# A project overlay, a stock one the FAT already ships, a stock one it does not,
# and a base DTB choice.
if run all "$loose_stone" \
  "[$(ov my-spi false),$(ov ucm-imx8m-plus-can true),$(ov ucm-imx8m-plus-rtc true)]" \
  '["devicetree_file=iot-gate-imx8plus.dtb"]'; then
  want='[{"in":"my-spi.dtbo","out":"overlays/my-spi.dtbo"},{"in":"ucm-imx8m-plus-rtc.dtbo","out":"overlays/ucm-imx8m-plus-rtc.dtbo"},{"in":"avocado-overlays.txt","out":"avocado-overlays.txt"}]'
  if [[ "$(appends all)" == "$want" ]]; then
    ok "project and unshipped stock overlays go under overlays/, the list at the root"
  else
    bad "files_append: $(appends all)"
  fi
  want=$'avocado_fdt_overlays=overlays/my-spi.dtbo ucm-imx8m-plus-can.dtbo overlays/ucm-imx8m-plus-rtc.dtbo\navocado_devicetree_file=iot-gate-imx8plus.dtb'
  if [[ "$(cat "$work/all/avocado-overlays.txt")" == "$want" ]]; then
    ok "list keeps manifest order and names a shipped stock overlay where it is"
  else
    bad "avocado-overlays.txt: $(cat "$work/all/avocado-overlays.txt")"
  fi
  if jq -e '(.overlays | all(.claimed_by == "avocado-ucm-imx8m-plus")) and .boot_config_claimed_by == "avocado-ucm-imx8m-plus"' \
    "$work/all/overlays.manifest.json" >/dev/null; then
    ok "every overlay and the boot_config are claimed"
  else
    bad "claims: $(cat "$work/all/overlays.manifest.json")"
  fi
else
  bad "hook refused a valid declaration: $(cat "$work/all/err")"
fi

# boot_config alone: no overlay list line, so U-Boot imports only the DTB choice.
if run dtonly "$loose_stone" '[]' '["devicetree_file = ucm-imx8m-plus.dtb"]'; then
  if [[ "$(cat "$work/dtonly/avocado-overlays.txt")" == "avocado_devicetree_file=ucm-imx8m-plus.dtb" ]]; then
    ok "boot_config alone writes only the DTB choice"
  else
    bad "$(cat "$work/dtonly/avocado-overlays.txt")"
  fi
else
  bad "boot_config alone refused: $(cat "$work/dtonly/err")"
fi

# refused <case> <stone> <overlays> <boot_config> <stderr pattern> <label>
refused() {
  if run "$1" "$2" "$3" "$4"; then
    bad "$6: hook accepted it"
  elif grep -q "$5" "$work/$1/err"; then
    ok "$6"
  else
    bad "$6: wrong error: $(cat "$work/$1/err")"
  fi
}

refused fit "$fit_stone" "[$(ov my-spi false)]" '[]' 'boots a FIT' \
  "a FIT board is refused (a loose overlay would sit outside the signature)"
refused key "$loose_stone" '[]' '["bootcmd=run evil"]' 'takes only' \
  "a boot_config key outside the allowlist is refused"
refused bare "$loose_stone" '[]' '["devicetree_file"]' 'takes only' \
  "a boot_config line without a value is refused"
refused missing "$loose_stone" '[]' '["devicetree_file=nope.dtb"]' 'ships no' \
  "a base DTB the boot FAT does not ship is refused at build time"
refused traversal "$loose_stone" '[]' '["devicetree_file=../Image"]' 'not a plain path' \
  "a base DTB path that leaves the FAT is refused"
refused twice "$loose_stone" '[]' '["devicetree_file=ucm-imx8m-plus.dtb","devicetree_file=iot-gate-imx8plus.dtb"]' \
  'more than once' "devicetree_file set twice is refused"
refused params "$loose_stone" \
  '[{"name":"x","file":"x.dtbo","params":{"speed":"1"},"stock":false,"claimed_by":null}]' '[]' \
  'has params' "overlay params are refused (fdt apply takes none)"
refused mismatch "$loose_stone" \
  '[{"name":"x","file":"y.dtbo","params":{},"stock":false,"claimed_by":null}]' '[]' \
  'must be <name>.dtbo' "a file that is not <name>.dtbo is refused"
refused empty "$loose_stone" '[]' '[]' 'no overlays or boot_config' \
  "an empty declaration is refused"

echo
echo "passed: $pass  failed: $fail"
[[ "$fail" -eq 0 ]]
