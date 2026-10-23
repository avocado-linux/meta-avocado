#!/usr/bin/env bash

# Standalone test for the Raspberry Pi capability file `boot-settings.json`.
# avocado-cli reads that file and fails a build that declares a kind of boot
# setting the board does not list, so what it lists has to be what the hook
# actually delivers, in both directions: a listed kind must be claimed by the
# real hook, and a kind the hook claims must be listed (otherwise the CLI
# refuses a project the hook would have served). Runs on any host with python3
# and jq. Not packaged into the recipe.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
hook="$here/../files/device-tree-overlay-deliver"
caps="$here/../files/boot-settings.json"

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

# The ids avocado-cli understands. A typo here is a kind nobody will ever ask
# for, so the board would silently advertise nothing.
known='["dt_overlay","dt_overlay_stock","boot_config","kernel_args"]'

if [[ ! -f "$caps" ]]; then
  bad "capability file is missing: $caps"
  echo
  echo "passed: $pass  failed: $fail"
  exit 1
fi

if jq -e --argjson known "$known" '
    .version == 1
    and (.kinds | type == "array" and length > 0)
    and (.kinds | all(type == "string"))
    and (.kinds | all(. as $k | $known | index($k) != null))
    and ((.kinds | length) == (.kinds | unique | length))
  ' "$caps" >/dev/null; then
  ok "capability file is version 1 with a list of known, unique kind ids"
else
  bad "capability file is malformed or names an unknown kind: $(cat "$caps")"
fi

listed() { jq -e --arg k "$1" '.kinds | index($k) != null' "$caps" >/dev/null; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

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

# Runs the real hook on one manifest. Leaves the claimed manifest in
# $work/<case>/overlays.manifest.json and the hook's stderr in .../err.
run_case() {
  local name="$1" manifest="$2"
  local d="$work/$name"
  mkdir -p "$d"
  : >"$d/spi.dtbo"
  printf '%s' "$manifest" >"$d/overlays.manifest.json"
  AVOCADO_DTBO_STAGING="$d" \
    AVOCADO_OVERLAYS_MANIFEST="$d/overlays.manifest.json" \
    AVOCADO_DELIVERY_FRAGMENT="$d/fragment.json" \
    AVOCADO_STONE_MANIFEST="$work/stone.json" \
    "$hook" >/dev/null 2>"$d/err"
}

# One manifest per hook-delivered kind, and the jq test that says the hook took it.
dt_manifest='{"version":1,"overlays":[{"name":"spi","file":"spi.dtbo","params":{},"stock":false,"claimed_by":null}],"boot_config":[],"boot_config_claimed_by":null}'
stock_manifest='{"version":1,"overlays":[{"name":"disable-bt","file":"disable-bt.dtbo","params":{},"stock":true,"claimed_by":null}],"boot_config":[],"boot_config_claimed_by":null}'
bc_manifest='{"version":1,"overlays":[],"boot_config":["dtparam=i2c_arm=on"],"boot_config_claimed_by":null}'
overlay_claimed='.overlays | length > 0 and all(.claimed_by != null)'
bc_claimed='.boot_config_claimed_by != null'

# claims <kind> <case> <manifest> <jq test>: the hook exits 0 and the test holds.
# A refusal is not a claim. Either way the answer must agree with the file.
check_kind() {
  local kind="$1" case_name="$2" manifest="$3" test="$4" claims=no
  if run_case "$case_name" "$manifest" \
    && jq -e "$test" "$work/$case_name/overlays.manifest.json" >/dev/null; then
    claims=yes
  fi
  if listed "$kind"; then
    if [[ "$claims" == yes ]]; then
      ok "$kind is listed and the hook claims it"
    else
      bad "$kind is listed but the hook does not claim it: $(cat "$work/$case_name/err" 2>/dev/null)"
    fi
  else
    if [[ "$claims" == yes ]]; then
      bad "$kind is not listed but the hook claims it: the CLI would refuse a project the hook can serve"
    else
      ok "$kind is not listed and the hook does not claim it"
    fi
  fi
}

check_kind dt_overlay dt "$dt_manifest" "$overlay_claimed"
check_kind dt_overlay_stock stock "$stock_manifest" "$overlay_claimed"
check_kind boot_config bc "$bc_manifest" "$bc_claimed"

# kernel_args is not delivered by this hook (a board applies it in its own build
# or provisioning step), so there is nothing to claim here. Listing it would
# have to be backed by that step, which this layer does not have today.
if listed kernel_args; then
  bad "kernel_args is listed but nothing in this layer applies kernel.cmdline*: no avocado-build hook reads it, and the Pi 5 stone manifest has no command-line variable"
fi

echo
echo "passed: $pass  failed: $fail"
[[ "$fail" -eq 0 ]]
