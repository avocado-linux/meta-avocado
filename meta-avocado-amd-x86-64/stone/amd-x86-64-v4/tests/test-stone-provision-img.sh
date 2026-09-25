#!/usr/bin/env bash
# Host test for stone-provision-img.sh: two helpers extracted from the script
# and run against temp files - size_to_mib (manifest size -> MiB) and
# write_image (dd a partition image into the disk image at its offset) - then
# the whole script against a small manifest.
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts, so bad runs only when the check failed
set -u
here=$(cd "$(dirname "$0")" && pwd); script=${1:-$here/../stone-provision-img.sh}
w=$(mktemp -d); trap 'rm -rf "$w"' EXIT
pass=0; fail=0; ok(){ echo "  ok   - $1"; pass=$((pass+1)); }; bad(){ echo "  FAIL - $1"; fail=$((fail+1)); }

for fn in size_to_mib write_image; do
  awk -v f="$fn" '$0 ~ "^"f"\\(\\) \\{" {on=1} on {print} on && /^}/ {exit}' "$script" >> "$w/fns.sh"
done
grep -q '^size_to_mib()' "$w/fns.sh" && grep -q '^write_image()' "$w/fns.sh" \
  || { echo "cannot extract the helpers from $script"; exit 2; }
call(){ bash -c "set -e; source '$w/fns.sh'; $*" 2>&1; }

# size_to_mib: whole MiB, rounded up, never zero.
for c in "512 KiB|1" "1024 KiB|1" "1536 KiB|2" "256 MiB|256" "2 GiB|2048" "08 MiB|8" "010 MiB|10"; do
  in=${c%|*}; want=${c#*|}; got=$(call "size_to_mib $in"); rc=$?
  { [ $rc -eq 0 ] && [ "$got" = "$want" ]; } && ok "size_to_mib $in = $want" || bad "size_to_mib $in: rc=$rc got=[$got] want=$want"
done
for c in "0 MiB" "abc MiB" "-4 MiB" "12 furlongs"; do
  got=$(call "size_to_mib $c"); rc=$?
  [ $rc -ne 0 ] && ok "size_to_mib rejects '$c'" || bad "size_to_mib '$c' accepted: [$got]"
done

# write_image: an image that fits lands at its offset; one that does not is
# refused before a byte is written, leaving the disk image as it was.
truncate -s 8M "$w/disk.img"; head -c 1048576 /dev/urandom > "$w/p.img"
out=$(call "write_image '$w/p.img' '$w/disk.img' 2 part 1"); rc=$?
{ [ $rc -eq 0 ] && cmp -s -n 1048576 -i 0:2097152 "$w/p.img" "$w/disk.img"; } \
  && ok "an image that fits is written at its offset" || bad "fits: rc=$rc out=[$out]"

truncate -s 8M "$w/disk2.img"; cp "$w/disk2.img" "$w/disk2.orig"
head -c $((1048576 + 1)) /dev/urandom > "$w/big.img"
out=$(call "write_image '$w/big.img' '$w/disk2.img' 2 rootfs-a 1"); rc=$?
{ [ $rc -ne 0 ] && cmp -s "$w/disk2.img" "$w/disk2.orig" && echo "$out" | grep -q "rootfs-a"; } \
  && ok "an image one byte larger than its partition is refused, disk untouched" || bad "too big: rc=$rc out=[$out]"

# The whole script, against a two-partition manifest and real sgdisk/dd on temp
# files. The USB script reuses any file at the final image path, so a build
# that fails part-way must leave nothing there.
build(){ mkdir -p "$w/b/build" "$w/b/data"; rm -f "$w/b/build/"*
  printf '%s' '{"runtime":{"platform":"t"},"storage_devices":{"rootdisk":{"images":{"a":"a.img","b":"b.img"},
    "partitions":[{"name":"p1","image":"a","size":1,"size_unit":"mebibytes"},
                  {"name":"p2","image":"b","size":1,"size_unit":"mebibytes"}]}}}' > "$w/b/m.json"
  AVOCADO_PROVISION_FWUP=no-such-fwup AVOCADO_STONE_MANIFEST="$w/b/m.json" AVOCADO_STONE_DATA_DIR="$w/b/data" \
    AVOCADO_STONE_BUILD_DIR="$w/b/build" bash "$script" 2>&1; }
head -c 4096 /dev/urandom > "$w/b-a.img"
mkdir -p "$w/b/data"; cp "$w/b-a.img" "$w/b/data/a.img"; rm -f "$w/b/data/b.img"
out=$(build); rc=$?
{ [ $rc -ne 0 ] && [ ! -e "$w/b/build/avocado-os-t.img" ]; } \
  && ok "a build that fails part-way leaves no image at the final path" || bad "partial: rc=$rc files=[$(ls "$w/b/build")] out=[$out]"

cp "$w/b-a.img" "$w/b/data/b.img"; out=$(build); rc=$?
{ [ $rc -eq 0 ] && [ -s "$w/b/build/avocado-os-t.img" ] && [ "$(ls "$w/b/build")" = "avocado-os-t.img" ]; } \
  && ok "a complete build publishes the image and nothing else" || bad "complete: rc=$rc files=[$(ls "$w/b/build")] out=[$out]"

# 16. With fwup installed the finished image is also wrapped in the archive
#     avocado-flash's fwup backend writes: <platform>-rootdisk.fw, whose
#     "complete" task raw-writes the image from offset 0. The stub records the
#     conf it was handed instead of building a real archive.
mkdir -p "$w/fwbin"
cat >"$w/fwbin/fwup" <<'S'
#!/bin/bash
conf=; out=
while [ $# -gt 0 ]; do case "$1" in -f) conf=$2; shift ;; -o) out=$2; shift ;; esac; shift; done
cp "$conf" "$out"
S
chmod +x "$w/fwbin/fwup"
build_fw(){ mkdir -p "$w/b/build"; rm -f "$w/b/build/"* "$w/b/build/".[!.]* 2>/dev/null
  AVOCADO_PROVISION_FWUP="$1" AVOCADO_STONE_MANIFEST="$w/b/m.json" AVOCADO_STONE_DATA_DIR="$w/b/data" \
    AVOCADO_STONE_BUILD_DIR="$w/b/build" bash "$script" 2>&1; }
out=$(build_fw "$w/fwbin/fwup"); rc=$?
fw="$w/b/build/t-rootdisk.fw"
{ [ $rc -eq 0 ] && [ -s "$fw" ] && grep -q "host-path = \"$w/b/build/avocado-os-t.img\"" "$fw" && grep -q 'raw_write(0)' "$fw" \
  && [ "$(find "$w/b/build" -mindepth 1 -printf '%f\n' | sort | tr '\n' ' ')" = "avocado-os-t.img t-rootdisk.fw " ]; } \
  && ok "the image is also wrapped in <platform>-rootdisk.fw for avocado-flash, nothing else left behind" \
  || bad "fwup archive: rc=$rc files=[$(ls -A "$w/b/build")] out=[$out]"

# 17. Without fwup the raw image is still the product, the run says why there is
#     no archive, and an archive from an earlier build does not survive to be
#     flashed in place of the new image.
out=$(mkdir -p "$w/b/build"; rm -f "$w/b/build/"*; echo stale >"$w/b/build/t-rootdisk.fw"
  AVOCADO_PROVISION_FWUP=no-such-fwup AVOCADO_STONE_MANIFEST="$w/b/m.json" AVOCADO_STONE_DATA_DIR="$w/b/data" \
    AVOCADO_STONE_BUILD_DIR="$w/b/build" bash "$script" 2>&1); rc=$?
{ [ $rc -eq 0 ] && [ -s "$w/b/build/avocado-os-t.img" ] && [ ! -e "$w/b/build/t-rootdisk.fw" ] && echo "$out" | grep -qi "fwup"; } \
  && ok "without fwup the raw image ships alone and a stale archive is removed" \
  || bad "no fwup: rc=$rc files=[$(ls -A "$w/b/build")] out=[$out]"

echo
echo "passed: $pass  failed: $fail  (checks: $((pass + fail))/17 run)"
[ "$fail" -eq 0 ] && [ $((pass + fail)) -eq 17 ]
