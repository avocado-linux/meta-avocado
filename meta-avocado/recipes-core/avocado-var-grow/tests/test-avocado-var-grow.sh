#!/usr/bin/env bash
# Host test with stubbed blkid/sgdisk/partx and a fake /sys + /dev tree: the
# grow runs only when GPT attribute 56 is set and the partition is short of the
# disk end; it preserves start/type/guid/name and re-sets the attribute.
set -u
here=$(cd "$(dirname "$0")" && pwd); script=$here/../files/avocado-var-grow
w=$(mktemp -d); trap 'rm -rf "$w"' EXIT
pass=0; fail=0; ok(){ echo "  ok   - $1"; pass=$((pass+1)); }; bad(){ echo "  FAIL - $1"; fail=$((fail+1)); }
mkdir -p "$w/bin" "$w/dev/disk/by-partlabel" "$w/sys/mmcblk9p9" "$w/sys/mmcblk9"
: > "$w/dev/mmcblk9"; : > "$w/dev/mmcblk9p9"; ln -s ../../mmcblk9p9 "$w/dev/disk/by-partlabel/var"
ln -s ../mmcblk9 "$w/sys/mmcblk9p9/.." 2>/dev/null; # parent dir already exists; emulate ".." via real dir
rmdir "$w/sys/mmcblk9p9" && mkdir -p "$w/sys/mmcblk9/mmcblk9p9" && ln -s mmcblk9/mmcblk9p9 "$w/sys/mmcblk9p9"
echo 9 > "$w/sys/mmcblk9/mmcblk9p9/partition"; echo 100000 > "$w/sys/mmcblk9/mmcblk9p9/start"; echo 720896 > "$w/sys/mmcblk9/mmcblk9p9/size"; echo 61071360 > "$w/sys/mmcblk9/size"
echo gpt > "$w/scheme"; echo 0x0100000000000000 > "$w/flags"
cat > "$w/bin/blkid" <<S
#!/bin/sh
case "\$*" in *PART_ENTRY_SCHEME*) cat "$w/scheme" ;; *PART_ENTRY_FLAGS*) cat "$w/flags" ;; esac
S
cat > "$w/bin/sgdisk" <<S
#!/bin/sh
echo "sgdisk \$*" >> "$w/log"
case "\$1" in -i) printf 'Partition GUID code: 0FC63DAF-8483-4772-8E79-3D69D8477DE4 (Linux filesystem)\nPartition unique GUID: 4D21B016-B534-45C2-A9FB-5C16E091FD2D\nFirst sector: 100000\nPartition name: '"'"'var'"'"'\n' ;; -d) echo 60971360 > "$w/sys/mmcblk9/mmcblk9p9/size" ;; esac
S
printf '#!/bin/sh\necho "partx $*" >> "%s/log"\n' "$w" > "$w/bin/partx"
chmod +x "$w/bin/"*
run(){ : > "$w/log"; PATH="$w/bin:$PATH" AVOCADO_VAR_GROW_DEVDIR="$w/dev" AVOCADO_VAR_GROW_DEV="$w/dev/disk/by-partlabel/var" AVOCADO_VAR_GROW_SYSBLOCK="$w/sys" sh "$script" 2>&1; }
out=$(run); rc=$?
{ [ $rc -eq 0 ] && grep -q "^sgdisk -e $w/dev/mmcblk9$" "$w/log" && grep -q "^sgdisk -d 9 -n 9:100000:0 -t 9:0FC63DAF-8483-4772-8E79-3D69D8477DE4 -u 9:4D21B016-B534-45C2-A9FB-5C16E091FD2D -c 9:var -A 9:=:0x0100000000000000 $w/dev/mmcblk9$" "$w/log" && grep -q "^partx --update --nr 9 $w/dev/mmcblk9$" "$w/log"; } && ok "marked partition short of the disk is extended in place, keeping start/type/guid/name/attribute" || bad "grow: rc=$rc $out $(cat "$w/log")"
out=$(run); { echo "$out" | grep -q "already extends" && [ ! -s "$w/log" ]; } && ok "a full-size partition is left alone (idempotent)" || bad "idempotent: $out"
echo 720896 > "$w/sys/mmcblk9/mmcblk9p9/size"; echo 0x0 > "$w/flags"
out=$(run); { echo "$out" | grep -q "not marked to grow" && [ ! -s "$w/log" ]; } && ok "without attribute 56 the partition stays as provisioned" || bad "unmarked: $out"
echo dos > "$w/scheme"; out=$(run); { echo "$out" | grep -q "not on a GPT disk" && [ ! -s "$w/log" ]; } && ok "an MBR disk is skipped" || bad "mbr: $out"
echo; echo "passed: $pass  failed: $fail"; [ "$fail" -eq 0 ]
