#!/usr/bin/env bash
# Prove stone-provision-direct.sh finds the kernel + initramfs in both qemu
# machines' stone manifests, and stages them under the role names the avocado
# CLI launches QEMU with.
#
# The two machines describe the same pair differently: qemuarm64 (U-Boot) names
# it only inside the boot FAT image's file list, as plain filenames; qemux86-64
# (UEFI) carries images.kernel/images.initramfs and its file list holds {in,out}
# objects, because the ESP stages the pair under bootloader-owned names. The
# script scanning only for plain strings is how the x86 direct profile broke
# once that machine moved to systemd-boot: jq printed raw JSON objects, nothing
# matched, and provisioning failed at "must include a kernel + initramfs entry".
#
# Runs the real scripts against the real manifests with a fabricated data dir.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STONE="$REPO_ROOT/meta-avocado-qemu/stone"

command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

failures=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; failures=$((failures + 1)); }
check() { if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (want '$3', got '$2')"; fi; }

# machine:expected kernel filename. The x86 entry is the regression guard —
# systemd-bootx64.efi sits in the same file list and must never win.
for spec in qemuarm64:Image qemux86-64:bzImage; do
    machine="${spec%%:*}"
    want_kernel="${spec#*:}"
    manifest="$STONE/stone-$machine.json"
    script="$STONE/$machine/stone-provision-direct.sh"

    src="$WORK/$machine/data"
    mkdir -p "$src"
    # Every filename the manifest mentions, so the script's copies succeed.
    while IFS= read -r name; do
        mkdir -p "$src/$(dirname "$name")"
        echo "$machine/$name" > "$src/$name"
    done < <(jq -r '.storage_devices.rootdisk.images | [.. | strings] | .[]' "$manifest")

    AVOCADO_STONE_MANIFEST="$manifest" \
    AVOCADO_STONE_DATA_DIR="$src" \
    AVOCADO_STONE_BUILD_DIR="$WORK/$machine/build" \
        bash "$script" >"$WORK/$machine.log" 2>&1 \
        || { fail "$machine: script exited $? ($(tail -1 "$WORK/$machine.log"))"; continue; }

    stage="$WORK/$machine/build/direct"
    out="$stage/manifest.json"
    check "$machine: kernel staged"    "$(jq -r .artifacts.kernel.file "$out")"    "$want_kernel"
    check "$machine: initramfs staged" "$(jq -r .artifacts.initramfs.file "$out")" \
          "avocado-image-initramfs-$machine.cpio.zst"
    # The CLI boots -kernel/-initrd through the role links, not the filenames.
    for role in kernel initramfs rootfs var; do
        if [ -f "$stage/$role" ]; then pass "$machine: $role link resolves"
        else fail "$machine: $role link missing or dangling"; fi
    done
done

if [ "$failures" -ne 0 ]; then
    printf '\n%d check(s) failed\n' "$failures"
    exit 1
fi
printf '\nall checks passed\n'
