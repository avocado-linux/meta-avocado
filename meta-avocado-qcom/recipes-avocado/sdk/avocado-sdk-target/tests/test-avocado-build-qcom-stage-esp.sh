#!/usr/bin/env bash
# Prove avocado-build-qcom hands the rebuilt ESP to provisioning as well as to
# stone bundle.
#
# Provisioning reads efi.bin from the stone dir (AVOCADO_STONE_DATA_DIR), and a
# Rubicon hub's provisioning bundle carries the stone dir but not the runtime
# input dir. An ESP staged only in the input dir works for a local provision,
# where stone-provision-ufs.sh falls back to the input dir, and fails every hub
# provision with "manifest declares images.efi as 'efi.bin' but no such file".
#
# The function body is extracted from the hook and run unmodified.
set -euo pipefail

HOOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/avocado-build-qcom"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

failures=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() {
  printf '  FAIL  %s\n' "$1"
  failures=$((failures + 1))
}
expect() {
  local what=$1
  shift
  if "$@"; then pass "$what"; else fail "$what"; fi
}

fn=$(sed -n '/^stage_esp() {/,/^}/p' "$HOOK")
expect "the hook defines stage_esp" [ -n "$fn" ]
eval "$fn"

input_dir="$WORK/runtimes/plain"
output_dir="$WORK/output/runtimes/plain/stone"
mkdir -p "$input_dir"
head -c 4096 /dev/urandom >"$WORK/efi-built.bin"

stage_esp "$WORK/efi-built.bin" efi.bin
expect "stone bundle's input dir has the ESP" cmp -s "$WORK/efi-built.bin" "$input_dir/efi.bin"
expect "the stone dir provisioning reads has the ESP" cmp -s "$WORK/efi-built.bin" "$output_dir/efi.bin"

# The hook must use it for the rebuilt ESP rather than copying to one place.
# shellcheck disable=SC2016 # the literal call text, not an expansion
expect "the rebuilt ESP goes through stage_esp" grep -q 'stage_esp "$esp_img" "$esp_image"' "$HOOK"

if [ $failures -gt 0 ]; then
  echo "$failures check(s) failed"
  exit 1
fi
echo "all checks passed"
