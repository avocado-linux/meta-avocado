#!/usr/bin/env bash
#
# validate-feed-local.sh - feed-validation pipeline for ONE package set.
#
# Thin entry over feed-validation-lib.sh: builds the machine, stages+renders
# the local feed (target + sdk repos), serves it, installs the given packages
# into an extension, and verifies (SDK tier, plus boot e2e with -b). For the
# multi-case test suite, use run-feed-validation.sh instead.
#
# Usage:
#   validate-feed-local.sh [-m MACHINE] [-l LIB_CSV] [-b] PKG [PKG...]
# Defaults: MACHINE=qemuarm64  LIB_CSV=""  boot=off
# Packages install into the scaffolded project's default `app` extension.
#
# Build front-end via AVOCADO_LOCAL_BUILD_CMD (default kas; override locally,
# e.g. in the workspace .envrc). See feed-validation-lib.sh for the full set of
# env overrides (AVOCADO_RELEASEVER, AVOCADO_REPO_URL, AVOCADO_LOCAL_BUILD_DIR).
#
set -euo pipefail
# shellcheck source=feed-validation-lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/feed-validation-lib.sh"

MACHINE=qemuarm64
LIB_CSV=""
BOOT=0
while getopts "m:l:b" opt; do
  case "$opt" in
    m) MACHINE="$OPTARG" ;;
    l) LIB_CSV="$OPTARG" ;;
    b) BOOT=1 ;;
    *)
      echo "usage: $0 [-m MACHINE] [-l LIB_CSV] [-b] PKG [PKG...]" >&2
      exit 2
      ;;
  esac
done
shift $((OPTIND - 1))
[ "$#" -ge 1 ] || fvl_die "no packages given (usage: $0 [opts] PKG [PKG...])"
PKGS=("$@")
PKG_CSV="$(
  IFS=,
  echo "${PKGS[*]}"
)"

# Work area on the big build disk (NOT /tmp; a full deploy is several GB and
# /tmp is often a size-capped tmpfs). Under build-<machine>/ which is gitignored.
WORK="${FVL_WORK_DIR:-$FVL_WORKSPACE/build-${MACHINE}/.fv-work}"
rm -rf "$WORK"
mkdir -p "$WORK"

# Shared fixtures.
deploy="$(fvl_build "$MACHINE")"
channel="$WORK/repo"
fvl_stage_and_render "$deploy" "$channel"
fvl_serve "$channel" "$MACHINE"

# SDK tier - scaffold a project, install into the app ext, verify.
proj="$WORK/proj"
fvl_scaffold_project "$MACHINE" "$proj"
fvl_log "Install + verify (SDK): ${PKGS[*]}"
if fvl_install_case "$MACHINE" "$proj" "${PKGS[@]}" \
  && fvl_verify_sdk_case "$MACHINE" "$proj" "$PKG_CSV" "$LIB_CSV"; then
  fvl_case_pass "sdk:${PKG_CSV}"
else
  fvl_case_fail "sdk:${PKG_CSV}" "package/lib missing in app ext sysroot"
fi

# Boot tier (optional).
if [ "$BOOT" -eq 1 ]; then
  fvl_log "Boot e2e: ${PKGS[*]}"
  if fvl_boot_verify_case "$MACHINE" "$WORK/proj-boot" "$PKG_CSV" "$LIB_CSV"; then
    fvl_case_pass "boot:${PKG_CSV}"
  else
    fvl_case_fail "boot:${PKG_CSV}" "ext/libs not present on booted target"
  fi
fi

fvl_serve_down
fvl_summary
