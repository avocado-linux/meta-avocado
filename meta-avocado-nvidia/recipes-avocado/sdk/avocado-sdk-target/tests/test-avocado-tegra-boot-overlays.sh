#!/usr/bin/env bash
# Host test with fixture engine directories: the build-time overlay check finds
# the engine in AVOCADO_STONE_INCLUDE_PATHS order before the runtime input dir,
# runs it isolated (-I -B), propagates its exit status, and treats a missing
# engine as a warning unless the manifest declares the OTA kernel dtb image.

# ok and bad only echo and increment, so `cond && ok || bad` cannot run both.
# shellcheck disable=SC2015
set -u
here=$(cd "$(dirname "$0")" && pwd)
script=$here/../avocado-tegra-boot-overlays
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

# A fixture engine: a package with __main__.py (the discovery marker) and a
# stub buildcheck that records who ran it, its flags and its arguments.
mkengine() { # <stone dir> <label> <exit status>
  local e=$1/tegraflash-engine/avocado_tegraflash
  mkdir -p "$e"
  : >"$e/__init__.py"
  : >"$e/__main__.py"
  cat >"$e/buildcheck.py" <<EOF
import sys
with open("$w/record", "w") as f:
    f.write("label=$2\n")
    f.write("isolated=%d dont_write_bytecode=%d\n" % (sys.flags.isolated, sys.flags.dont_write_bytecode))
    f.write("engine_last=%s\n" % sys.path[-1])
    f.write("args=%s\n" % " ".join(sys.argv[1:]))
sys.exit($3)
EOF
}

in=$w/in
sdk=$w/sdk
inc1=$w/inc1
inc2=$w/inc2
mkdir -p "$in" "$sdk/stone" "$inc1" "$inc2"
printf '{"storage_devices":{"rootdisk":{"images":{"rootfs":"r.img"}}}}' >"$w/plain.json"
printf '{"storage_devices":{"rootdisk":{"images":{"kernel_dtb_ota":"k.img"}}}}' >"$w/ota.json"
# The key as a plain string elsewhere is not a declaration.
printf '{"note":"kernel_dtb_ota","storage_devices":{"rootdisk":{"images":{"rootfs":"r.img"}}}}' >"$w/mention.json"

run() { # <include paths> <manifest>
  rm -f "$w/record"
  env -u PYTHONPATH AVOCADO_STONE_INCLUDE_PATHS="$1" AVOCADO_SDK_PREFIX="$sdk" bash "$script" "$in" "$2" 2>&1
}

mkengine "$inc1" inc1 0
mkengine "$inc2" inc2 0
mkengine "$in" input 0
mkengine "$sdk/stone" sdk 0
msg=$(run "$inc1:$inc2" "$w/plain.json")
rc=$?
{ [ $rc -eq 0 ] && grep -q '^label=inc1$' "$w/record"; } && ok "the first include path wins over later paths, the input dir and the SDK" || bad "include order: rc=$rc $msg"
grep -q "^engine_last=$inc1/tegraflash-engine$" "$w/record" && ok "the engine dir is appended to sys.path" || bad "engine dir not last on sys.path"
grep -q '^isolated=1 dont_write_bytecode=1$' "$w/record" && ok "python runs with -I -B" || bad "flags: $(cat "$w/record")"
grep -q "^args=--input-dir $in --manifest $w/plain.json --include-paths $inc1:$inc2 --sdk-stone-dir $sdk/stone$" "$w/record" && ok "the module gets input dir, manifest, include paths and SDK stone dir" || bad "args: $(cat "$w/record")"

rm -rf "$inc1/tegraflash-engine"
msg=$(run "$inc1:$inc2" "$w/plain.json")
rc=$?
{ [ $rc -eq 0 ] && grep -q '^label=inc2$' "$w/record"; } && ok "an include path without an engine is skipped" || bad "skip: rc=$rc $msg"

msg=$(run "" "$w/plain.json")
rc=$?
{ [ $rc -eq 0 ] && grep -q '^label=input$' "$w/record" && grep -q -- '--include-paths  --sdk-stone-dir' "$w/record"; } && ok "the input dir engine is used when no include path carries one" || bad "input dir: rc=$rc $msg"

rm -rf "$in/tegraflash-engine"
msg=$(run "" "$w/plain.json")
rc=$?
{ [ $rc -eq 0 ] && grep -q '^label=sdk$' "$w/record"; } && ok "the SDK stone dir is the last resort" || bad "sdk: rc=$rc $msg"

# Propagation: a failing module fails the helper.
mkengine "$inc1" failing 7
msg=$(run "$inc1" "$w/plain.json")
rc=$?
[ $rc -eq 7 ] && ok "a non-zero module status propagates" || bad "status: rc=$rc $msg"

# No engine anywhere.
rm -rf "$inc1/tegraflash-engine" "$inc2/tegraflash-engine" "$sdk/stone/tegraflash-engine"
msg=$(run "$inc1:$inc2" "$w/plain.json")
rc=$?
{ [ $rc -eq 0 ] && [[ $msg == *WARNING* ]] && [[ $msg == *"$inc1"* ]] && [[ $msg == *"$inc2"* ]] && [[ $msg == *"$in"* ]] && [[ $msg == *"$sdk/stone"* ]]; } && ok "no engine warns, names the searched dirs and exits 0" || bad "no engine: rc=$rc $msg"

msg=$(run "$inc1:$inc2" "$w/mention.json")
rc=$?
[ $rc -eq 0 ] && ok "the key as a mere string value does not make the OTA image required" || bad "mention: rc=$rc $msg"

msg=$(run "$inc1:$inc2" "$w/ota.json")
rc=$?
{ [ $rc -eq 1 ] && [[ $msg == *"$inc1"* ]] && [[ $msg == *"$sdk/stone"* ]]; } && ok "no engine with kernel_dtb_ota declared exits 1 naming the dirs" || bad "ota no engine: rc=$rc $msg"

# python3 older than 3.10 counts as no engine.
mkengine "$inc1" old 0
mkdir -p "$w/oldpy"
printf '#!/bin/sh\nexit 1\n' >"$w/oldpy/python3"
chmod +x "$w/oldpy/python3"
rm -f "$w/record"
msg=$(env -u PYTHONPATH PATH="$w/oldpy:$PATH" AVOCADO_STONE_INCLUDE_PATHS="$inc1" AVOCADO_SDK_PREFIX="$sdk" bash "$script" "$in" "$w/plain.json" 2>&1)
rc=$?
{ [ $rc -eq 0 ] && [[ $msg == *WARNING* ]] && [ ! -e "$w/record" ]; } && ok "python3 older than 3.10 warns and skips the module" || bad "old python: rc=$rc $msg"

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
