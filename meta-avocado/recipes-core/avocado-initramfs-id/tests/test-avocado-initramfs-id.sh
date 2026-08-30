#!/usr/bin/env bash
# Host test with a fake release tree: the initramfs id is published to /run when
# the release files carry one, the first readable file wins, and a missing or
# empty id publishes nothing rather than an empty file the reader would have to
# distinguish from a real value.
set -u
here=$(cd "$(dirname "$0")" && pwd); script=$here/../files/avocado-initramfs-id
w=$(mktemp -d); trap 'rm -rf "$w"' EXIT
pass=0; fail=0; ok(){ echo "  ok   - $1"; pass=$((pass+1)); }; bad(){ echo "  FAIL - $1"; fail=$((fail+1)); }
mkdir -p "$w/root/etc" "$w/root/usr/lib" "$w/out"
out="$w/out/dir/initramfs-build-id"
run(){ rm -rf "$w/out/dir"; AVOCADO_INITRAMFS_ID_OUT="$out" AVOCADO_INITRAMFS_ID_ROOT="$w/root" sh "$script" 2>&1; }

printf 'ID=avocado\nAVOCADO_OS_BUILD_ID=initramfs-abc\n' > "$w/root/usr/lib/initrd-release"
msg=$(run); rc=$?
{ [ $rc -eq 0 ] && [ "$(cat "$out")" = "initramfs-abc" ]; } && ok "the id is published to /run, creating the directory" || bad "publish: rc=$rc $msg $(cat "$out" 2>&1)"

# /etc/initrd-release is normally a symlink to the usr/lib copy, but when both
# exist as real files the reader must not have to guess which one it got.
printf 'AVOCADO_OS_BUILD_ID="initramfs-etc"\n' > "$w/root/etc/initrd-release"
msg=$(run); { [ "$(cat "$out")" = "initramfs-etc" ]; } && ok "/etc/initrd-release wins and quotes are stripped" || bad "precedence: $msg $(cat "$out" 2>&1)"
rm -f "$w/root/etc/initrd-release"

printf 'ID=avocado\nVERSION_ID=0.0.0\n' > "$w/root/usr/lib/initrd-release"
: > "$w/root/usr/lib/os-release-initrd"
msg=$(run); rc=$?
{ [ $rc -eq 0 ] && [ ! -e "$out" ] && echo "$msg" | grep -q "not publishing"; } && ok "no id in the release files publishes nothing and still exits 0" || bad "absent: rc=$rc $msg"

printf 'AVOCADO_OS_BUILD_ID=\n' > "$w/root/usr/lib/initrd-release"
msg=$(run); { [ ! -e "$out" ]; } && ok "an empty id is not published as an empty file" || bad "empty: $msg $(cat "$out" 2>&1)"

# An old initramfs has no release file at all: absence must be silent-safe.
rm -f "$w/root/usr/lib/initrd-release" "$w/root/usr/lib/os-release-initrd"
msg=$(run); rc=$?
{ [ $rc -eq 0 ] && [ ! -e "$out" ]; } && ok "no release files at all still exits 0" || bad "no files: rc=$rc $msg"

echo; echo "passed: $pass  failed: $fail"; [ $fail -eq 0 ]
