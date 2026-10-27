#!/usr/bin/env bash
# Host test for stone-provision-img.sh: the whole script against a small
# manifest shaped like qemux86-64's - a FAT `boot` image with two files under
# nested loader/ dirs, and `rootfs`/`var` given as plain filename strings.
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts, so bad runs only when the check failed
set -u
here=$(cd "$(dirname "$0")" && pwd)
script=${1:-$here/../stone-provision-img.sh}
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

missing=""
for t in jq sgdisk mkfs.fat mcopy mmd mtype; do
  command -v "$t" >/dev/null 2>&1 || missing="$missing $t"
done
if [ -n "$missing" ]; then
  echo "needs on PATH:$missing (gdisk, dosfstools, mtools)"
  exit 2
fi

# mmd on an existing directory prompts on /dev/tty, which hangs a provision run
# with a tty and is invisible without one. The stub records a repeat instead of
# prompting; its exit status alone would not do, since the script ignores it.
real_mmd=$(command -v mmd)
mkdir -p "$w/bin"
cat >"$w/bin/mmd" <<S
#!/usr/bin/env bash
dir=\${!#}
if grep -qxF -- "\$dir" "$w/mmd.log" 2>/dev/null; then
  echo "\$dir" >>"$w/mmd.dup"
  exit 1
fi
echo "\$dir" >>"$w/mmd.log"
exec "$real_mmd" "\$@" </dev/null
S
chmod +x "$w/bin/mmd"

mkdir -p "$w/data" "$w/build"
echo kernel >"$w/data/k"
echo "timeout 0" >"$w/data/l.conf"
echo "title t" >"$w/data/e.conf"
head -c 4096 /dev/urandom >"$w/data/r.img"
head -c 4096 /dev/urandom >"$w/data/v.img"
cat >"$w/m.json" <<'J'
{"runtime": {"platform": "t"},
 "storage_devices": {"rootdisk": {
   "images": {
     "boot": {"out": "boot.img", "size": 64,
              "build_args": {"type": "fat", "files": [
                {"in": "k", "out": "bzImage"},
                {"in": "l.conf", "out": "loader/loader.conf"},
                {"in": "e.conf", "out": "loader/entries/avocado.conf"}]}},
     "rootfs": "r.img",
     "var": "v.img"},
   "partitions": [
     {"name": "boot-a", "image": "boot", "partition_type": "EF00", "offset": 1, "offset_unit": "mebibytes", "size": 64, "size_unit": "mebibytes"},
     {"name": "rootfs-a", "image": "rootfs", "partition_type": "8304", "size": 1, "size_unit": "mebibytes"},
     {"name": "var", "image": "var", "partition_type": "8300", "size": 1, "size_unit": "mebibytes"}]}}}
J

out=$(PATH="$w/bin:$PATH" AVOCADO_STONE_MANIFEST="$w/m.json" AVOCADO_STONE_DATA_DIR="$w/data" \
  AVOCADO_STONE_BUILD_DIR="$w/build" bash "$script" </dev/null 2>&1)
rc=$?
img="$w/build/avocado-os-t.img"

# 1. jq indexing a plain-string image as an object exits 5 under set -e.
{ [ $rc -eq 0 ] && [ -s "$img" ]; } \
  && ok "a manifest with plain-string rootfs/var images builds the disk image" \
  || bad "build: rc=$rc out=[$out]"

# 2. loader/loader.conf and loader/entries/avocado.conf share ::/loader.
{ [ ! -e "$w/mmd.dup" ] && grep -qxF "::/loader" "$w/mmd.log" && grep -qxF "::/loader/entries" "$w/mmd.log"; } \
  && ok "each ESP directory is created once" \
  || bad "mmd repeated: [$(cat "$w/mmd.dup" 2>/dev/null)] log=[$(cat "$w/mmd.log" 2>/dev/null)]"

# 3. The ESP is boot-a, at 1 MiB in the disk image.
esp_ok=1
for c in "bzImage|k" "loader/loader.conf|l.conf" "loader/entries/avocado.conf|e.conf"; do
  [ "$(mtype -i "$img@@1M" "::/${c%|*}" 2>/dev/null)" = "$(cat "$w/data/${c#*|}")" ] || esp_ok=0
done
[ $esp_ok -eq 1 ] && ok "the ESP holds each boot file at its path" \
  || bad "ESP: [$(mdir -/ -b -i "$img@@1M" ::/ 2>&1)]"

# 4. rootfs-a follows boot-a at 65 MiB, var at 66 MiB.
{ cmp -s -n 4096 -i 0:$((65 * 1048576)) "$w/data/r.img" "$img" \
  && cmp -s -n 4096 -i 0:$((66 * 1048576)) "$w/data/v.img" "$img"; } \
  && ok "plain-string images are written at their partition offsets" \
  || bad "rootfs/var not at their offsets"

echo
echo "passed: $pass  failed: $fail  (checks: $((pass + fail))/4 run)"
[ "$fail" -eq 0 ] && [ $((pass + fail)) -eq 4 ]
