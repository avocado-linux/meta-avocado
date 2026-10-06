#!/usr/bin/env bash
# Host test for qemuwrapper-native's rootfs-escape check: a binary runs only
# when its loader and every library resolve inside the rootfs, symlinks
# followed. Builds a throwaway rootfs from the host's own loader and libc and
# runs /usr/bin/true through the wrapper.
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts
set -u
here=$(cd "$(dirname "$0")" && pwd)
wrapper=${1:-$here/../files/qemuwrapper-native}
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

[ "$(uname -m)" = x86_64 ] || {
  echo "needs an x86-64 host"
  exit 2
}
bin=/usr/bin/true
host_ld=$(realpath -e /lib64/ld-linux-x86-64.so.2)
host_libc=$(ldd "$bin" | awk '$1 == "libc.so.6" { print $3 }')
host_libc=$(realpath -e "$host_libc")

# rootfs <name>: loader and libc as real files, the layout the wrapper expects.
rootfs() {
  r="$w/$1"
  mkdir -p "$r/lib" "$r/usr/lib"
  cp "$host_ld" "$r/lib/ld-linux-x86-64.so.2"
  cp "$host_libc" "$r/usr/lib/libc.so.6"
  echo "$r"
}
run() { sh "$wrapper" -L "$1" "$bin" 2>&1; }

r=$(rootfs good)
out=$(run "$r") && ok "runs when loader and libc are inside the rootfs" \
  || bad "good rootfs refused: $out"

r=$(rootfs abs-lib)
ln -sf "$host_libc" "$r/usr/lib/libc.so.6"
! out=$(run "$r") && echo "$out" | grep -q 'libc.so.6' \
  && ok "refuses a library that is an absolute symlink out of the rootfs" \
  || bad "absolute-symlink libc accepted: $out"

r=$(rootfs rel-lib)
mv "$r/usr/lib/libc.so.6" "$r/usr/lib/libc-real.so.6"
ln -s libc-real.so.6 "$r/usr/lib/libc.so.6"
out=$(run "$r") && ok "accepts a relative symlink that stays inside the rootfs" \
  || bad "relative in-rootfs symlink refused: $out"

r=$(rootfs abs-ld)
ln -sf "$host_ld" "$r/lib/ld-linux-x86-64.so.2"
! out=$(run "$r") && echo "$out" | grep -q 'resolves outside' \
  && ok "refuses a loader that is an absolute symlink out of the rootfs" \
  || bad "absolute-symlink loader accepted: $out"

r=$(rootfs missing)
rm "$r/usr/lib/libc.so.6"
! out=$(run "$r") && ok "refuses when a library is not found" || bad "missing libc accepted: $out"

echo "test-qemuwrapper-native: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
