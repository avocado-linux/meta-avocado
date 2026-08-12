#!/usr/bin/env bash

# Standalone test for the QEMU device-tree overlay delivery hook.
# Runs on any host with python3 + jq. Feeds the hook a staged manifest and a
# fake qemuarm64 stone manifest, then checks the emitted fragment and the
# claimed_by annotations. Not packaged into the recipe.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
hook="$here/../files/device-tree-overlay-deliver"

pass=0
fail=0
ok()  { printf '  ok   - %s\n' "$1"; pass=$((pass + 1)); }
bad() { printf '  FAIL - %s\n' "$1"; fail=$((fail + 1)); }

for t in python3 jq; do
    command -v "$t" >/dev/null 2>&1 || { echo "SKIP: host missing $t"; exit 0; }
done
[[ -x "$hook" ]] || { echo "FAIL - hook not executable: $hook"; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

staging="$work/staging"
mkdir -p "$staging"
: > "$staging/my-spi.dtbo"

cat > "$staging/overlays.manifest.json" <<'EOF'
{
  "version": 1,
  "overlays": [
    {"name": "my-spi", "file": "my-spi.dtbo", "params": {}, "claimed_by": null}
  ]
}
EOF

# qemuarm64-shaped stone manifest: a FAT boot image identified by its kernel
# (Image), no config.txt.
cat > "$work/stone.json" <<'EOF'
{
  "runtime": {"platform": "avocado-qemuarm64"},
  "storage_devices": {
    "rootdisk": {
      "images": {
        "bios": "flash.bin",
        "boot": {
          "build_args": {
            "type": "fat",
            "files": ["avocado-image-initramfs-qemuarm64.cpio.zst", "Image"]
          }
        },
        "rootfs": "rootfs.erofs"
      }
    }
  }
}
EOF

fragment="$work/delivery.overlay.json"
run() {
    AVOCADO_DTBO_STAGING="$staging" \
    AVOCADO_OVERLAYS_MANIFEST="$staging/overlays.manifest.json" \
    AVOCADO_DELIVERY_FRAGMENT="$fragment" \
    AVOCADO_STONE_MANIFEST="$work/stone.json" \
        "$hook"
}

if run >/dev/null 2>"$work/run.err"; then
    fa='.storage_devices.rootdisk.images.boot.build_args.files_append'
    if [[ "$(jq -r "${fa} | length" "$fragment")" == "2" ]] \
        && jq -e "${fa}[] | select(.out == \"overlays/my-spi.dtbo\" and .in == \"my-spi.dtbo\")" "$fragment" >/dev/null \
        && jq -e "${fa}[] | select(.out == \"avocado-overlays.txt\")" "$fragment" >/dev/null; then
        ok "fragment appends the .dtbo and the overlay list to the kernel-bearing boot FAT"
    else
        bad "fragment files_append is wrong: $(jq -c "$fa" "$fragment")"
    fi

    # The boot script cannot enumerate a directory, so the list it imports has
    # to name every overlay - by name, since the script owns the overlays/
    # prefix and the .dtbo suffix.
    if grep -qx 'avocado_fdt_overlays=my-spi' "$staging/avocado-overlays.txt"; then
        ok "overlay list names every delivered overlay for the boot script"
    else
        bad "overlay list wrong: [$(cat "$staging/avocado-overlays.txt" 2>/dev/null)]"
    fi

    claimed="$(jq -r '[.overlays[] | select(.claimed_by == "avocado-qemuarm64")] | length' "$staging/overlays.manifest.json")"
    if [[ "$claimed" == "1" ]]; then
        ok "overlay is marked claimed_by the platform"
    else
        bad "claimed_by not set correctly (got $claimed of 1)"
    fi
else
    bad "hook failed on valid input: $(cat "$work/run.err")"
fi

# Negative: a stone manifest whose FAT ships no kernel is a hard error.
cat > "$work/stone-nokernel.json" <<'EOF'
{"runtime": {"platform": "x"}, "storage_devices": {"d": {"images": {"boot": {"build_args": {"type": "fat", "files": ["config.txt"]}}}}}}
EOF
if AVOCADO_DTBO_STAGING="$staging" \
   AVOCADO_OVERLAYS_MANIFEST="$staging/overlays.manifest.json" \
   AVOCADO_DELIVERY_FRAGMENT="$work/frag2.json" \
   AVOCADO_STONE_MANIFEST="$work/stone-nokernel.json" \
       "$hook" >/dev/null 2>"$work/nokernel.err"; then
    bad "hook accepted a manifest with no kernel-bearing FAT (should hard-error)"
else
    if grep -qi "kernel" "$work/nokernel.err"; then
        ok "no kernel-bearing FAT is a hard error"
    else
        bad "no-kernel failed without a clear message: $(cat "$work/nokernel.err")"
    fi
fi

# Negative: two kernel-bearing FAT images is ambiguous. The loop returns the
# first match in document order, so which FAT receives the overlays would be
# decided by textual position in the stone JSON - a reserved slot filled in
# above the boot slot would silently take delivery and the booted image would
# ship without them.
cat > "$work/stone-twofat.json" <<'EOF'
{
  "runtime": {"platform": "avocado-qemuarm64"},
  "storage_devices": {
    "rootdisk": {
      "images": {
        "recovery": {"build_args": {"type": "fat", "files": ["Image"]}},
        "boot": {"build_args": {"type": "fat", "files": ["Image"]}}
      }
    }
  }
}
EOF
if AVOCADO_DTBO_STAGING="$staging" \
   AVOCADO_OVERLAYS_MANIFEST="$staging/overlays.manifest.json" \
   AVOCADO_DELIVERY_FRAGMENT="$work/frag-twofat.json" \
   AVOCADO_STONE_MANIFEST="$work/stone-twofat.json" \
       "$hook" >/dev/null 2>"$work/twofat.err"; then
    bad "two kernel-bearing FATs were accepted (target chosen by document order)"
else
    if grep -qi 'more than one\|ambiguous\|recovery' "$work/twofat.err"; then
        ok "two kernel-bearing FAT images is a hard error naming both"
    else
        bad "ambiguous FAT failed without a clear message: $(cat "$work/twofat.err")"
    fi
fi

echo
echo "passed: $pass  failed: $fail"
[[ "$fail" -eq 0 ]]
