#!/usr/bin/env bash
# Host test for how stone-provision-img.sh sizes a partition in the flashed
# image: an explicit size wins, even on an "expand" partition, and only a
# sizeless partition is sized from its own image. Runs the real sizing block,
# lifted out of every intel-x86-64 copy of the script, against a small manifest.
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts
set -u
here=$(cd "$(dirname "$0")" && pwd)
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

# 3 MiB plus a byte, so sizing from the image rounds up to 4.
head -c $((3 * 1048576 + 1)) /dev/zero >"$w/var.img"
cat >"$w/manifest.json" <<'EOF'
{"storage_devices": {"rootdisk": {"images": {"var": "var.img"}}}}
EOF

found=0
for script in "$here"/../intel-x86-64-v*/stone-provision-img.sh; do
  [ -f "$script" ] || continue
  found=$((found + 1))
  rel=${script#"$here"/../}
  : >"$w/fns.sh"
  for fn in size_to_mib resolve_image_filename; do
    awk -v f="$fn" '$0 ~ "^"f"\\(\\) \\{" {on=1} on {print} on && /^}/ {exit}' "$script" >>"$w/fns.sh"
  done
  # The sizing block: from the size test to its closing fi, at loop indent.
  awk '/^    if .*"\$size" = "null"/ {on=1} on {print} on && /^    fi$/ {exit}' \
    "$script" >"$w/block.sh"
  grep -q '^size_to_mib()' "$w/fns.sh" && grep -q '^resolve_image_filename()' "$w/fns.sh" \
    && grep -q 'size_mib=' "$w/block.sh" \
    || {
      bad "$rel: cannot extract the sizing code"
      continue
    }

  # size_of <size> <unit> <expand> <image> -> prints size_mib, or fails
  size_of() {
    MANIFEST="$w/manifest.json" DATA_DIR="$w" bash -c '
      set -e
      . "$1"
      name=var size=$2 size_unit=$3 expand=$4 image=$5
      . "$6"
      echo "$size_mib"
    ' _ "$w/fns.sh" "$1" "$2" "$3" "$4" "$w/block.sh" 2>&1
  }

  got=$(size_of 64 mebibytes true var)
  [ "$got" = "64" ] && ok "$rel: explicit size wins on an expand partition" \
    || bad "$rel: expand+size gave [$got], want 64"

  got=$(size_of null null true var)
  [ "$got" = "4" ] && ok "$rel: sizeless expand partition is sized from its image" \
    || bad "$rel: sizeless expand gave [$got], want 4"

  got=$(size_of 16 mebibytes "" "")
  [ "$got" = "16" ] && ok "$rel: plain sized partition keeps its size" \
    || bad "$rel: plain size gave [$got], want 16"

  got=$(size_of null null true "")
  echo "$got" | grep -q 'no size and no image' \
    && ok "$rel: sizeless partition with no image is refused" \
    || bad "$rel: sizeless without image: [$got]"
done

[ "$found" -ge 3 ] || bad "found $found copies of stone-provision-img.sh, expected 3"

echo "test-stone-img-sizing: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
