#!/usr/bin/env bash

# Standalone test for the Qualcomm capability file `boot-settings.json`.
# avocado-cli reads that file and fails a build that declares a kind of boot
# setting the board does not list, so what it lists has to be what the hook
# actually delivers, in both directions: a listed kind must be claimed by the
# real hook, and a kind the hook cannot deliver must not be listed (and one it
# can deliver must be, or the CLI refuses a project the hook could serve).
# Runs on any host with python3 and jq. Not packaged into the recipe.

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

# A device tree blob the hook accepts: FDT magic, total size equal to the file.
valid_dtbo() { printf '\xd0\x0d\xfe\xed\x00\x00\x00\x0c\x00\x00\x00\x00' >"$1"; }

# Runs the real hook, through bash because the file in the tree is not
# executable (the recipe installs it 0755). Leaves the claimed manifest in
# $work/<case>/overlays.manifest.json and the hook's stderr in .../err.
# $3 is "stage" to put a valid overlay blob in the staging directory.
run_case() {
  local name="$1" manifest="$2" stage="$3"
  local d="$work/$name"
  mkdir -p "$d"
  [[ "$stage" == stage ]] && valid_dtbo "$d/spi.dtbo"
  printf '%s' "$manifest" >"$d/overlays.manifest.json"
  AVOCADO_DTBO_STAGING="$d" \
    AVOCADO_OVERLAYS_MANIFEST="$d/overlays.manifest.json" \
    AVOCADO_DELIVERY_FRAGMENT="$d/fragment.json" \
    AVOCADO_STONE_MANIFEST="$work/stone.json" \
    bash "$hook" >/dev/null 2>"$d/err"
}

dt_manifest='{"version":1,"overlays":[{"name":"spi","file":"spi.dtbo","params":{},"stock":false,"claimed_by":null}],"boot_config":[],"boot_config_claimed_by":null}'
# The CLI stages nothing for a stock overlay, so the blob is absent.
stock_manifest='{"version":1,"overlays":[{"name":"gone","file":"gone.dtbo","params":{},"stock":true,"claimed_by":null}],"boot_config":[],"boot_config_claimed_by":null}'
# The hook never reads boot_config; a compiled overlay rides along so the hook
# has something it accepts, and the lines must stay unclaimed.
bc_manifest='{"version":1,"overlays":[{"name":"spi","file":"spi.dtbo","params":{},"stock":false,"claimed_by":null}],"boot_config":["a=b"],"boot_config_claimed_by":null}'

overlay_claimed='.overlays | length > 0 and all(.claimed_by != null)'
bc_claimed='.boot_config_claimed_by != null'

# check_kind <kind> <case> <manifest> <stage|nostage> <jq claim test> [expected refusal text]
# Either way the hook's answer must agree with the file.
check_kind() {
  local kind="$1" case_name="$2" manifest="$3" stage="$4" test="$5" refusal="${6:-}" claims=no
  if run_case "$case_name" "$manifest" "$stage" \
    && jq -e "$test" "$work/$case_name/overlays.manifest.json" >/dev/null; then
    claims=yes
  elif [[ -n "$refusal" ]] && ! grep -q "$refusal" "$work/$case_name/err" 2>/dev/null; then
    bad "$kind: the hook did not claim it, but not for the expected reason ($refusal): $(cat "$work/$case_name/err" 2>/dev/null)"
    return
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

check_kind dt_overlay dt "$dt_manifest" stage "$overlay_claimed"
check_kind dt_overlay_stock stock "$stock_manifest" nostage "$overlay_claimed" "was not staged"
check_kind boot_config bc "$bc_manifest" stage "$bc_claimed"

# kernel_args is applied by avocado-build-qcom from the environment, outside
# this hook, so there is nothing to claim here.
if listed kernel_args; then
  ok "kernel_args is listed (applied by avocado-build-qcom; not checkable here)"
else
  bad "kernel_args is not listed, but avocado-build-qcom applies AVOCADO_KERNEL_CMDLINE and AVOCADO_KERNEL_CMDLINE_EXTRA"
fi

echo
echo "passed: $pass  failed: $fail"
[[ "$fail" -eq 0 ]]
