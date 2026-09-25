#!/usr/bin/env bash
# Host test for two helpers in stone-provision-img.sh, extracted from the
# script and run against temp files: size_to_mib (manifest size -> MiB) and
# write_image (dd a partition image into the disk image at its offset).
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts, so bad runs only when the check failed
set -u
here=$(cd "$(dirname "$0")" && pwd); script=$here/../stone-provision-img.sh
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

echo
echo "passed: $pass  failed: $fail  (checks: $((pass + fail))/13 run)"
[ "$fail" -eq 0 ] && [ $((pass + fail)) -eq 13 ]
