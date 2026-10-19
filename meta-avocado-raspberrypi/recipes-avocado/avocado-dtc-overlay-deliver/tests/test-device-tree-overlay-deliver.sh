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
ok() {
  printf '  ok   - %s\n' "$1"
  pass=$((pass + 1))
}
bad() {
  printf '  FAIL - %s\n' "$1"
  fail=$((fail + 1))
}

for t in python3 jq; do
  command -v "$t" >/dev/null 2>&1 || {
    echo "SKIP: host missing $t"
    exit 0
  }
done
[[ -x "$hook" ]] || {
  echo "FAIL - hook not executable: $hook"
  exit 1
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

staging="$work/staging"
mkdir -p "$staging"
: >"$staging/my-spi.dtbo"
: >"$staging/leds.dtbo"

cat >"$staging/overlays.manifest.json" <<'EOF'
{
  "version": 1,
  "overlays": [
    {"name": "my-spi", "file": "my-spi.dtbo", "params": {"speed": "12000000", "cs": "0"}, "claimed_by": null},
    {"name": "leds", "file": "leds.dtbo", "params": {}, "claimed_by": null}
  ]
}
EOF

# Minimal RPi-shaped stone manifest: a FAT image that ships config.txt.
cat >"$work/stone.json" <<'EOF'
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
cat >"$work/stone-nofat.json" <<'EOF'
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

# Negative: an overlay whose delivered name collides with one the BSP already
# ships must be refused. stone treats an identical (in, out) pair as an
# idempotent duplicate and drops the append, then resolves the name from the
# SDK's stone dir first - so the STOCK blob ships and the user's overlay is
# silently absent from the image while claimed_by still satisfies the CLI gate.
cat >"$work/stone-stock.json" <<'EOF'
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
              {"in": "my-spi.dtbo", "out": "overlays/my-spi.dtbo"}
            ]
          }
        }
      }
    }
  }
}
EOF
if AVOCADO_DTBO_STAGING="$staging" \
  AVOCADO_OVERLAYS_MANIFEST="$staging/overlays.manifest.json" \
  AVOCADO_DELIVERY_FRAGMENT="$work/frag-stock.json" \
  AVOCADO_STONE_MANIFEST="$work/stone-stock.json" \
  "$hook" >/dev/null 2>"$work/stock.err"; then
  bad "an overlay colliding with a stock .dtbo was accepted (stone drops it silently)"
else
  if grep -qi 'my-spi\|already ships\|collide' "$work/stock.err"; then
    ok "an overlay colliding with a stock .dtbo is refused by name"
  else
    bad "collision failed without naming the overlay: $(cat "$work/stock.err")"
  fi
fi

# Negative: two FAT images both shipping config.txt is ambiguous. The loop
# returns whichever comes first in document order, so the delivery target would
# be decided by textual position in the stone JSON rather than by intent.
cat >"$work/stone-twofat.json" <<'EOF'
{
  "runtime": {"platform": "avocado-raspberrypi5"},
  "storage_devices": {
    "rootdisk": {
      "images": {
        "recovery": {
          "build_args": {
            "type": "fat",
            "files": [{"in": "bootfiles/config.txt", "out": "config.txt"}]
          }
        },
        "boot": {
          "build_args": {
            "type": "fat",
            "files": [{"in": "bootfiles/config.txt", "out": "config.txt"}]
          }
        }
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
  bad "two config.txt-bearing FATs were accepted (target chosen by document order)"
else
  if grep -qi 'more than one\|ambiguous\|recovery' "$work/twofat.err"; then
    ok "two config.txt-bearing FAT images is a hard error naming both"
  else
    bad "ambiguous FAT failed without a clear message: $(cat "$work/twofat.err")"
  fi
fi

# boot_config and stock overlays. Each case gets its own staging directory so a
# manifest the hook rewrote in one case cannot leak into the next.
run_case() { # <name> <manifest-json> <stone-json>
  local case_dir="$work/case-$1"
  mkdir -p "$case_dir"
  printf '%s\n' "$2" >"$case_dir/overlays.manifest.json"
  printf '%s\n' "$3" >"$case_dir/stone.json"
  : >"$case_dir/custom.dtbo"
  AVOCADO_DTBO_STAGING="$case_dir" \
    AVOCADO_OVERLAYS_MANIFEST="$case_dir/overlays.manifest.json" \
    AVOCADO_DELIVERY_FRAGMENT="$case_dir/fragment.json" \
    AVOCADO_STONE_MANIFEST="$case_dir/stone.json" \
    "$hook" >"$case_dir/out" 2>"$case_dir/err"
}

stone_plain="$(cat "$work/stone.json")"
stone_ships_bt="$(jq -c '.storage_devices.rootdisk.images.boot.build_args.files += [{"in": "disable-bt.dtbo", "out": "overlays/disable-bt.dtbo"}]' "$work/stone.json")"

# boot_config alone, no overlays: the hook must still deliver the include file.
if run_case bc '{"version": 1, "overlays": [], "boot_config": ["dtparam=i2c_arm=on", "usb_max_current_enable=1"], "boot_config_claimed_by": null}' "$stone_plain"; then
  d="$work/case-bc"
  if [[ "$(cat "$d/avocado-overlays.txt")" == $'dtparam=i2c_arm=on\nusb_max_current_enable=1' ]] \
    && [[ "$(jq -c "$fa" "$d/fragment.json")" == '[{"in":"avocado-overlays.txt","out":"avocado-overlays.txt"}]' ]] \
    && [[ "$(jq -r '.boot_config_claimed_by' "$d/overlays.manifest.json")" == "avocado-raspberrypi5" ]]; then
    ok "boot_config alone is written to the include file and claimed"
  else
    bad "boot_config-only delivery wrong: txt=$(cat "$d/avocado-overlays.txt") fa=$(jq -c "$fa" "$d/fragment.json")"
  fi
else
  bad "hook rejected a boot_config-only manifest: $(cat "$work/case-bc/err")"
fi

# A stock overlay the boot FAT does not ship is appended from the BSP's own
# files, boot_config lines come before every dtoverlay line, and a custom
# overlay beside it is delivered as before.
if run_case mix '{"version": 1, "overlays": [{"name": "disable-bt", "file": "disable-bt.dtbo", "params": {}, "stock": true, "claimed_by": null}, {"name": "custom", "file": "custom.dtbo", "params": {"a": "1"}, "stock": false, "claimed_by": null}], "boot_config": ["dtparam=i2c_arm=on"], "boot_config_claimed_by": null}' "$stone_plain"; then
  d="$work/case-mix"
  if [[ "$(cat "$d/avocado-overlays.txt")" == $'dtparam=i2c_arm=on\ndtoverlay=disable-bt\ndtoverlay=custom,a=1' ]] \
    && jq -e "${fa}[] | select(.in == \"disable-bt.dtbo\" and .out == \"overlays/disable-bt.dtbo\")" "$d/fragment.json" >/dev/null \
    && jq -e "${fa}[] | select(.in == \"custom.dtbo\" and .out == \"overlays/custom.dtbo\")" "$d/fragment.json" >/dev/null \
    && [[ "$(jq -r "$fa | length" "$d/fragment.json")" == "3" ]]; then
    ok "stock overlay is appended from the BSP files and boot_config precedes dtoverlay lines"
  else
    bad "stock plus custom delivery wrong: txt=$(cat "$d/avocado-overlays.txt") fa=$(jq -c "$fa" "$d/fragment.json")"
  fi
else
  bad "hook rejected a stock overlay the BSP can supply: $(cat "$work/case-mix/err")"
fi

# A stock overlay the boot FAT already ships is neither refused (the collision
# rule is for custom overlays) nor appended a second time.
if run_case shipped '{"version": 1, "overlays": [{"name": "disable-bt", "file": "disable-bt.dtbo", "params": {}, "stock": true, "claimed_by": null}], "boot_config": [], "boot_config_claimed_by": null}' "$stone_ships_bt"; then
  d="$work/case-shipped"
  if [[ "$(jq -c "$fa" "$d/fragment.json")" == '[{"in":"avocado-overlays.txt","out":"avocado-overlays.txt"}]' ]] \
    && [[ "$(cat "$d/avocado-overlays.txt")" == "dtoverlay=disable-bt" ]] \
    && [[ "$(jq -r '.overlays[0].claimed_by' "$d/overlays.manifest.json")" == "avocado-raspberrypi5" ]]; then
    ok "a stock overlay already on the boot FAT is referenced but not appended again"
  else
    bad "shipped stock overlay handled wrong: fa=$(jq -c "$fa" "$d/fragment.json")"
  fi
else
  bad "hook refused a stock overlay the BSP already ships: $(cat "$work/case-shipped/err")"
fi

# Nothing to deliver is an invocation error, not a silent success.
if run_case empty '{"version": 1, "overlays": [], "boot_config": [], "boot_config_claimed_by": null}' "$stone_plain"; then
  bad "hook accepted a manifest with neither overlays nor boot_config"
else
  if grep -q 'no overlays or boot_config' "$work/case-empty/err"; then
    ok "an empty manifest is a hard error"
  else
    bad "empty manifest failed without a clear message: $(cat "$work/case-empty/err")"
  fi
fi

echo
echo "passed: $pass  failed: $fail"
[[ "$fail" -eq 0 ]]
