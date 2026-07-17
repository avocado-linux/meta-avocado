#!/usr/bin/env bash

# Standalone test for the Raspberry Pi device-tree overlay delivery hook.
# Runs on any host with python3 + jq. Feeds the hook a staged manifest and a
# fake stone manifest, then checks the emitted fragment, the include file, and
# the claimed_by annotations. Not packaged into the recipe.

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
: > "$staging/leds.dtbo"

cat > "$staging/overlays.manifest.json" <<'EOF'
{
  "version": 1,
  "overlays": [
    {"name": "my-spi", "file": "my-spi.dtbo", "params": {"speed": "12000000", "cs": "0"}, "claimed_by": null},
    {"name": "leds", "file": "leds.dtbo", "params": {}, "claimed_by": null}
  ]
}
EOF

# Minimal RPi-shaped stone manifest: a FAT image that ships config.txt.
cat > "$work/stone.json" <<'EOF'
{
  "runtime": {"platform": "avocado-raspberrypi5"},
  "storage_devices": {
    "rootdisk": {
      "images": {
        "boot": {
          "build_args": {
            "type": "fat",
            "files": [
              {"in": "bootfiles/config.txt", "out": "config.txt"},
              "Image"
            ]
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
    # Fragment targets the discovered device/image and appends both .dtbo files
    # plus the include file, all as new outputs (no config.txt rewrite).
    fa='.storage_devices.rootdisk.images.boot.build_args.files_append'
    if [[ "$(jq -r "$fa | length" "$fragment")" == "3" ]] \
        && jq -e "${fa}[] | select(.out == \"overlays/my-spi.dtbo\" and .in == \"my-spi.dtbo\")" "$fragment" >/dev/null \
        && jq -e "${fa}[] | select(.out == \"overlays/leds.dtbo\")" "$fragment" >/dev/null \
        && jq -e "${fa}[] | select(.out == \"avocado-overlays.txt\" and .in == \"avocado-overlays.txt\")" "$fragment" >/dev/null; then
        ok "fragment appends both .dtbo files and the include file to the boot FAT"
    else
        bad "fragment files_append is wrong: $(jq -c "$fa" "$fragment")"
    fi

    # config.txt is NOT touched by the fragment.
    if jq -e '.. | objects | select(.out? == "config.txt")' "$fragment" >/dev/null 2>&1; then
        bad "fragment rewrites config.txt (must be additive only)"
    else
        ok "fragment does not rewrite config.txt"
    fi

    # Include file carries a dtoverlay line per overlay, params sorted+appended.
    if grep -qx 'dtoverlay=my-spi,cs=0,speed=12000000' "$staging/avocado-overlays.txt" \
        && grep -qx 'dtoverlay=leds' "$staging/avocado-overlays.txt"; then
        ok "avocado-overlays.txt has correct dtoverlay lines with sorted params"
    else
        bad "avocado-overlays.txt wrong: $(cat "$staging/avocado-overlays.txt")"
    fi

    # Both overlays are now claimed by the platform.
    claimed="$(jq -r '[.overlays[] | select(.claimed_by == "avocado-raspberrypi5")] | length' "$staging/overlays.manifest.json")"
    if [[ "$claimed" == "2" ]]; then
        ok "both overlays are marked claimed_by the platform"
    else
        bad "claimed_by not set correctly (got $claimed of 2)"
    fi
else
    bad "hook failed on valid input: $(cat "$work/run.err")"
fi

# Negative: a stone manifest with no config.txt-bearing FAT is a hard error.
cat > "$work/stone-nofat.json" <<'EOF'
{"runtime": {"platform": "x"}, "storage_devices": {"d": {"images": {"rootfs": "rootfs.erofs"}}}}
EOF
if AVOCADO_DTBO_STAGING="$staging" \
   AVOCADO_OVERLAYS_MANIFEST="$staging/overlays.manifest.json" \
   AVOCADO_DELIVERY_FRAGMENT="$work/frag2.json" \
   AVOCADO_STONE_MANIFEST="$work/stone-nofat.json" \
       "$hook" >/dev/null 2>"$work/nofat.err"; then
    bad "hook accepted a manifest with no config.txt FAT (should hard-error)"
else
    if grep -qi "config.txt" "$work/nofat.err"; then
        ok "no-boot-FAT is a hard error"
    else
        bad "no-FAT failed without a clear message: $(cat "$work/nofat.err")"
    fi
fi

echo
echo "passed: $pass  failed: $fail"
[[ "$fail" -eq 0 ]]
