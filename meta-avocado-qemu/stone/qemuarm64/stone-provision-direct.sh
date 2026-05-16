#!/usr/bin/env bash
#
# direct provisioning profile
# ---------------------------
# Stage the build's individual boot artifacts (kernel, initramfs, rootfs, var)
# as loose files so the avocado CLI can launch QEMU with -kernel/-initrd and
# raw virtio-blk drives. No fwup archive, no GPT, no A/B slots, no bootloader.
#
# Intended consumer: the avocado-vm helper VM the CLI runs on a dev host.
#
# Environment variables provided by avocado:
#   AVOCADO_STONE_MANIFEST   - path to stone-<target>.json
#   AVOCADO_STONE_BUILD_DIR  - build output directory (where we stage by default)
#   AVOCADO_STONE_DATA_DIR   - stone data directory (source of the artifacts;
#                              stone create copies them here from the SDK)
#   AVOCADO_PROVISION_OUT    - (optional) final output directory
#   AVOCADO_CMDLINE_EXTRA    - (optional) extra kernel cmdline appended to default

set -euo pipefail

manifest="$AVOCADO_STONE_MANIFEST"
src="${AVOCADO_STONE_DATA_DIR:?AVOCADO_STONE_DATA_DIR must be set}"
stage="${AVOCADO_STONE_BUILD_DIR}/direct"

mkdir -p "$stage"

# Pull artifact filenames from the manifest. boot.build_args.files is an array
# containing both the kernel (Image or bzImage) and the initramfs (cpio.zst).
kernel_name=""
initramfs_name=""
while IFS= read -r f; do
    case "$f" in
        Image|bzImage|vmlinuz*) kernel_name="$f" ;;
        *initramfs*)            initramfs_name="$f" ;;
    esac
done < <(jq -r '.storage_devices.rootdisk.images.boot.build_args.files[]' "$manifest")

if [ -z "$kernel_name" ] || [ -z "$initramfs_name" ]; then
    echo "manifest's boot.build_args.files must include a kernel + initramfs entry" >&2
    exit 1
fi

rootfs_name=$(jq -r '.storage_devices.rootdisk.images.rootfs' "$manifest")
var_name=$(jq -r    '.storage_devices.rootdisk.images.var'    "$manifest")
platform=$(jq -r    '.runtime.platform'                       "$manifest")
arch=$(jq -r        '.runtime.architecture'                   "$manifest")

# Per-arch serial console default. Kept here, not in the manifest, because it's
# a QEMU/boot concern not a runtime contract.
case "$arch" in
    arm64)  console="ttyAMA0" ;;
    x86_64) console="ttyS0"   ;;
    *)      console="ttyS0"   ;;
esac

# Stage with original filenames (for traceability) + a stable alias for the role.
stage_one() {
    local role="$1" filename="$2"
    cp -v "$src/$filename" "$stage/$filename"
    ln -sf "$filename" "$stage/$role"
}

stage_one kernel    "$kernel_name"
stage_one initramfs "$initramfs_name"
stage_one rootfs    "$rootfs_name"
stage_one var       "$var_name"

# manifest.json — the contract between this profile and the avocado CLI.
sha() { sha256sum "$1" | awk '{print $1}'; }

cat > "$stage/manifest.json" <<EOF
{
  "format": "avocado-direct",
  "format_version": 1,
  "platform": "$platform",
  "architecture": "$arch",
  "artifacts": {
    "kernel":    { "file": "$kernel_name",    "role_link": "kernel",    "sha256": "$(sha "$stage/$kernel_name")",    "type": "kernel" },
    "initramfs": { "file": "$initramfs_name", "role_link": "initramfs", "sha256": "$(sha "$stage/$initramfs_name")", "type": "initramfs-cpio-zst" },
    "rootfs":    { "file": "$rootfs_name",    "role_link": "rootfs",    "sha256": "$(sha "$stage/$rootfs_name")",    "type": "erofs-lz4" },
    "var":       { "file": "$var_name",       "role_link": "var",       "sha256": "$(sha "$stage/$var_name")",       "type": "btrfs" }
  },
  "cmdline_default": "console=$console root=/dev/vda rw ${AVOCADO_CMDLINE_EXTRA:-}",
  "qemu_hint": {
    "machine": "virt",
    "boot": "direct",
    "kernel": "kernel",
    "initrd": "initramfs",
    "drives": [
      { "id": "rootfs", "file": "rootfs", "format": "raw", "if": "virtio", "readonly": true },
      { "id": "var",    "file": "var",    "format": "raw", "if": "virtio" }
    ]
  }
}
EOF

echo
echo "direct provisioning staged at: $stage"

# Mirror to AVOCADO_PROVISION_OUT if requested (matches img profile behavior).
if [ -n "${AVOCADO_PROVISION_OUT:-}" ]; then
    echo "copying to AVOCADO_PROVISION_OUT=$AVOCADO_PROVISION_OUT"
    mkdir -p "$AVOCADO_PROVISION_OUT"
    cp -av "$stage/." "$AVOCADO_PROVISION_OUT/"
fi
