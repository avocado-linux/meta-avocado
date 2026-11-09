#!/usr/bin/env bash
# Prove avocado-build-x86 applies the project's kernel cmdline to the x86
# systemd-boot entry: appended once however often the build runs, replaced
# outright on request, restored when the project drops it, and re-based when a
# reinstall puts a fresh packaged entry back.
set -euo pipefail

HOOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/avocado-build-x86"
command -v jq >/dev/null 2>&1 || {
  echo "SKIP: host missing jq"
  exit 0
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
export AVOCADO_PREFIX="$WORK/prefix" AVOCADO_SDK_PREFIX="$WORK/sdk"
mkdir -p "$AVOCADO_PREFIX/runtimes/rt" "$AVOCADO_SDK_PREFIX/stone"
echo '{"storage_devices":{"rootdisk":{"images":{}}}}' >"$AVOCADO_SDK_PREFIX/stone/stone-intel-x86-64-v2.json"
entry="$AVOCADO_PREFIX/runtimes/rt/avocado.conf"
shipped='options root=PARTLABEL=rootfs-a ro console=ttyS0,115200n8'
ship() { printf 'title Avocado OS\nlinux /bzImage\n%s\n' "$shipped" >"$entry"; }
run() { env -u AVOCADO_KERNEL_CMDLINE -u AVOCADO_KERNEL_CMDLINE_EXTRA "$@" bash "$HOOK" intel-x86-64-v2 rt >/dev/null 2>"$WORK/err"; }
opts() { sed -n 's/^options //p' "$entry"; }

failures=0
check() {
  if [ "$2" = "$3" ]; then printf '  PASS  %s\n' "$1"; else
    printf '  FAIL  %s\n        want: %s\n        got:  %s\n' "$1" "$3" "$2"
    failures=$((failures + 1))
  fi
}

ship
run
check "no project cmdline leaves the entry as shipped" "$(opts)" "${shipped#options }"

run AVOCADO_KERNEL_CMDLINE_EXTRA=quiet
run AVOCADO_KERNEL_CMDLINE_EXTRA=quiet
check "cmdline_extra is appended once across rebuilds" "$(opts)" "${shipped#options } quiet"
check "the rest of the entry is kept" "$(sed -n 2p "$entry")" "title Avocado OS"

run AVOCADO_KERNEL_CMDLINE="root=PARTLABEL=rootfs-a ro" AVOCADO_KERNEL_CMDLINE_EXTRA=x=1
check "cmdline replaces the line, extra appends to it" "$(opts)" "root=PARTLABEL=rootfs-a ro x=1"

run
check "dropping the project cmdline restores the shipped line" "$(opts)" "${shipped#options }"

shipped='options root=PARTLABEL=rootfs-a ro console=tty0'
ship
run AVOCADO_KERNEL_CMDLINE_EXTRA=quiet
check "a reinstalled entry becomes the new base" "$(opts)" "root=PARTLABEL=rootfs-a ro console=tty0 quiet"

rm -f "$entry" "$entry.orig"
if run AVOCADO_KERNEL_CMDLINE_EXTRA=quiet; then
  check "a cmdline with no boot entry fails the build" "succeeded" "failed"
else
  check "a cmdline with no boot entry fails the build" "failed" "failed"
fi

if [ "$failures" -eq 0 ]; then
  echo "all passed"
else
  echo "$failures failed"
  exit 1
fi
