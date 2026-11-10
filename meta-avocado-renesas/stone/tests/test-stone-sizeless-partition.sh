#!/usr/bin/env bash
# Host test for how the build-disk-image.sh scripts size a partition that has no
# size in the manifest (var, which stone grows on the target): it is sized from
# its own image, an explicit size still wins, and a sizeless partition with no
# usable image is refused. Runs the real guard, lifted out of each script, so a
# script that loses it fails here.
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts
set -u
here=$(cd "$(dirname "$0")" && pwd)
root=${AVOCADO_TEST_ROOT:-$(cd "$here/../../.." && pwd)}
w=$(mktemp -d)
trap 'rm -rf "$w"' EXIT
pass=0
fail=0
ok() {
  echo "  ok   - $1"
  pass=$((pass + 1))
}
bad() {
  echo "  FAIL - $1"
  fail=$((fail + 1))
}

command -v jq >/dev/null || {
  echo "jq not installed"
  exit 2
}

# 3 MiB plus a byte, so sizing from the image rounds up.
head -c $((3 * 1048576 + 1)) /dev/zero >"$w/var.img"
cat >"$w/manifest.json" <<'EOF'
{"storage_devices": {"rootdisk": {"images": {"var": "var.img"}}}}
EOF

# script dir | size variable | size helper | 64 MiB explicit | sizeless result
# (the rockchip script rounds to 4 MiB and counts 512-byte sectors)
cases=(
  "meta-avocado-renesas/stone/rzv2n-sr-som size_mib size_to_mib 64 4"
  "meta-avocado-alif/stone/alif-e8-devkit size_kib size_to_kib 65536 4096"
  "meta-avocado-stm/stone/stm32mp25-dk size_kib size_to_kib 65536 4096"
  "meta-avocado-rockchip/stone/orangepi-5-plus size_sec size_to_sectors 131072 8192"
)

ran=0
for c in "${cases[@]}"; do
  read -r dir var helper want_explicit want_sizeless <<<"$c"
  script=$root/$dir/build-disk-image.sh
  : >"$w/fns.sh"
  for fn in "$helper" resolve_image_filename; do
    awk -v f="$fn" '$0 ~ "^"f"\\(\\) \\{" {on=1} on {print} on && /^}/ {exit}' "$script" >>"$w/fns.sh" 2>/dev/null
  done
  # The guard: from the size test to the fi at the same indent.
  awk '!on && /^[[:space:]]*if .*"\$size" = "null"/ {on=1; match($0, /^[[:space:]]*/); ind=substr($0, 1, RLENGTH)}
       on {print} on && $0 == ind "fi" {exit}' \
    "$script" >"$w/block.sh" 2>/dev/null
  grep -q "^$helper()" "$w/fns.sh" && grep -q '^resolve_image_filename()' "$w/fns.sh" \
    && grep -q "$var=" "$w/block.sh" \
    || {
      bad "$dir: cannot extract the sizing code"
      continue
    }

  # size_of <size> <unit> <image> -> prints the size variable, or the error
  size_of() {
    MANIFEST="$w/manifest.json" DATA_DIR="$w" bash -c '
      set -e
      . "$1"
      name=var size=$2 size_unit=$3 image=$4
      . "$5"
      echo "${!6}"
    ' _ "$w/fns.sh" "$1" "$2" "$3" "$w/block.sh" "$var" 2>&1
  }

  ran=$((ran + 1))
  got=$(size_of 64 mebibytes "")
  [ "$got" = "$want_explicit" ] && ok "$dir: an explicit size is kept" \
    || bad "$dir: explicit size gave [$got], want $want_explicit"

  ran=$((ran + 1))
  got=$(size_of null null var)
  [ "$got" = "$want_sizeless" ] && ok "$dir: a sizeless partition is sized from its image" \
    || bad "$dir: sizeless gave [$got], want $want_sizeless"

  ran=$((ran + 1))
  got=$(size_of null null "")
  echo "$got" | grep -q 'no size and no image' \
    && ok "$dir: a sizeless partition with no image is refused" \
    || bad "$dir: sizeless without image: [$got]"

  ran=$((ran + 1))
  got=$(size_of null null nosuchkey)
  echo "$got" | grep -q 'image not found' \
    && ok "$dir: a sizeless partition whose image file is missing is refused" \
    || bad "$dir: sizeless with a missing image: [$got]"
done

echo
echo "passed: $pass  failed: $fail  (checks: $ran/16 run)"
[ "$fail" -eq 0 ] && [ "$ran" -eq 16 ]
