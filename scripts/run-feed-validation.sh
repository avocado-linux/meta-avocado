#!/usr/bin/env bash
#
# run-feed-validation.sh - run the local feed-validation test suite.
#
# Builds the machine and stages/renders/serves the local feed ONCE (shared
# fixtures), then runs every case from the cases file: the SDK tier
# (install + verify in an extension) for all cases, plus the boot e2e for
# cases marked boot=yes. Reports PASS/FAIL per case and exits non-zero on any
# failure, so it drops into CI / goal loops cleanly.
#
# Usage: run-feed-validation.sh [-m MACHINE] [-c CASES_FILE]
# Defaults: MACHINE=qemuarm64  CASES_FILE=<scripts>/feed-validation-cases
#
# Build front-end via AVOCADO_LOCAL_BUILD_CMD (default kas; override locally).
# See feed-validation-lib.sh for env overrides.
#
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=feed-validation-lib.sh
source "$DIR/feed-validation-lib.sh"

MACHINE=qemuarm64
CASES_FILE="$DIR/feed-validation-cases"
while getopts "m:c:" opt; do
  case "$opt" in
    m) MACHINE="$OPTARG" ;;
    c) CASES_FILE="$OPTARG" ;;
    *)
      echo "usage: $0 [-m MACHINE] [-c CASES_FILE]" >&2
      exit 2
      ;;
  esac
done
[ -f "$CASES_FILE" ] || fvl_die "cases file not found: $CASES_FILE"

# Work area on the big build disk (NOT /tmp; see validate-feed-local.sh).
WORK="${FVL_WORK_DIR:-$FVL_WORKSPACE/build-${MACHINE}/.fv-work}"
rm -rf "$WORK"
mkdir -p "$WORK"

# Shared fixtures (once for the whole suite).
deploy="$(fvl_build "$MACHINE")"
channel="$WORK/repo"
fvl_stage_and_render "$deploy" "$channel"
fvl_serve "$channel" "$MACHINE"

# Run cases. Redirection (not a pipe) keeps the pass/fail counters in this shell.
while IFS='|' read -r name pkgs libs boot; do
  name="$(echo "${name:-}" | xargs)"
  [ -z "$name" ] && continue
  case "$name" in \#*) continue ;; esac
  pkgs="$(echo "${pkgs:-}" | xargs)"
  libs="$(echo "${libs:-}" | xargs | tr ' ' ',')"
  boot="$(echo "${boot:-}" | xargs)"
  [ -n "$pkgs" ] || {
    fvl_case_fail "$name" "no packages listed"
    continue
  }
  read -ra parr <<<"$pkgs"
  local_csv="${pkgs// /,}"
  proj="$WORK/proj-$name"

  fvl_log "Case: $name (packages: $pkgs)"
  fvl_scaffold_project "$MACHINE" "$proj"
  if fvl_install_case "$MACHINE" "$proj" "${parr[@]}" \
    && fvl_verify_sdk_case "$MACHINE" "$proj" "$local_csv" "$libs"; then
    fvl_case_pass "sdk:$name"
  else
    fvl_case_fail "sdk:$name" "install/verify failed"
  fi

  if [ "$boot" = "yes" ]; then
    if fvl_boot_verify_case "$MACHINE" "$WORK/proj-$name-boot" "$local_csv" "$libs"; then
      fvl_case_pass "boot:$name"
    else
      fvl_case_fail "boot:$name" "boot e2e failed"
    fi
  fi
done <"$CASES_FILE"

fvl_serve_down
fvl_summary
