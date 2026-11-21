#!/usr/bin/env bash
# Feed/scan sstate parity for one machine.
#
# A CVE scan build stacks kas/feature/cve-check.yml on a feed configuration
# and expects to take nearly every task from the feed's sstate. A setting in
# cve-check.yml that changes a task signature the feed configuration does not
# makes that work rebuild. This parses both stacks, dumps every task signature
# of the target without building (bitbake -S none), and compares them.
#
# Feed: machine, complete.yml, sbom.yml, ci/mirrors.yml (complete.yml and
# sbom.yml only when present). Scan: the feed chain plus cve-check.yml and a
# cve-assess.yml fragment setting AVOCADO_CVE_REPORT_STATUS = "All". Both
# mirror the chains the build farm composes for a feed build and for its CVE
# scan, and must change when those do. Build-host overlays (fetch, memory,
# PARALLEL_MAKE) are left out: they are the same in both stacks and none of
# them is in a task signature.
#
# Usage:
#   scripts/feed-scan-parity.sh dump <machine> [build-dir]
#     Parse both stacks. Exit 0 when both dumps were written, 2 otherwise.
#   scripts/feed-scan-parity.sh compare [build-dir]
#     Exit 1 when a compared task differs, 0 when none does, 2 on error.
#   scripts/feed-scan-parity.sh explain [build-dir]
#     bitbake-diffsigs output for a few differing tasks. Diagnostics only:
#     exits 0 whatever happens, so it can never change the verdict.
#
# PARITY_PARSE_THREADS caps bitbake's parser processes (default: CPU count).
set -uo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TARGET=avocado-distro

die() {
  echo "feed-scan-parity: $*" >&2
  exit 2
}

build_dir() { echo "${1:-${REPO}/build-parity}"; }

dump() {
  local machine=${1:-} build
  [ -n "${machine}" ] || die "usage: dump <machine> [build-dir]"
  [ -f "${REPO}/kas/machine/${machine}.yml" ] || die "no kas/machine/${machine}.yml"
  build=$(build_dir "${2:-}")
  bash "${REPO}/scripts/init-build" "${REPO}/kas/machine/${machine}.yml" "${build}" >/dev/null \
    || die "init-build failed"
  cd "${build}" || die "no ${build}"

  # Generated fragments live in the layer because kas wants every file of a
  # chain in one repo. Removed on exit; the pinned versions below keep the
  # dirty tree out of every signature.
  local assess="${REPO}/kas/ci/cve-assess.yml" parity="${REPO}/kas/ci/parity.yml"
  trap 'rm -f "'"${assess}"'" "'"${parity}"'"' EXIT
  # Byte for byte what the scan task writes.
  printf 'header:\n  version: 14\nlocal_conf_header:\n  %s: |\n    %s\n' \
    zzz-cve-assess 'AVOCADO_CVE_REPORT_STATUS = "All"' >"${assess}"
  # Both stacks get this, so it cannot make them differ:
  # - OEBasicHash: with no equivalences recorded, OEEquivHash computes the same
  #   task hashes; this makes that hold without a hash server or its database.
  # - BB_SRCREV_POLICY cache: an AUTOREV recipe resolves once, so an upstream
  #   push between the two parses cannot look like drift.
  {
    printf 'header:\n  version: 14\nlocal_conf_header:\n  zzzz-parity: |\n'
    printf '    BB_SIGNATURE_HANDLER = "OEBasicHash"\n'
    printf '    BB_HASHSERVE = ""\n'
    printf '    BB_SRCREV_POLICY = "cache"\n'
    if [ -n "${PARITY_PARSE_THREADS:-}" ]; then
      printf '    BB_NUMBER_PARSE_THREADS = "%s"\n' "${PARITY_PARSE_THREADS}"
    fi
  } >"${parity}"

  local feed="${REPO}/kas/machine/${machine}.yml" frag
  for frag in complete sbom; do
    if [ -f "${REPO}/kas/feature/${frag}.yml" ]; then
      feed="${feed}:${REPO}/kas/feature/${frag}.yml"
    else
      echo "WARNING: kas/feature/${frag}.yml absent; feed builds go without it too"
    fi
  done
  feed="${feed}:${REPO}/kas/ci/mirrors.yml"
  local scan="${feed}:${REPO}/kas/feature/cve-check.yml:${assess}"
  [ -f "${REPO}/kas/feature/cve-check.yml" ] || die "no kas/feature/cve-check.yml to compare against"

  # Fixed, so the composed version (which reads the layer's git state) is the
  # same for both stacks and across runs.
  export DISTRO_CODENAME=parity/ci DISTRO_VERSION=0.0 BUILD_ID=0

  # kas puts TOPDIR in build/; each multiconfig has its own TMPDIR there.
  rm -rf parity build/tmp*/stamps
  local stack chain t0 d
  for stack in feed scan; do
    if [ "${stack}" = feed ]; then chain="${feed}:${parity}"; else chain="${scan}:${parity}"; fi
    echo "=== ${stack}: bitbake -S none ${TARGET}"
    echo "    ${chain//${REPO}\//}"
    t0=$(date +%s)
    kas shell "${chain}" -c "bitbake -S none ${TARGET}" \
      || die "the ${stack} stack did not parse; this is not a signature difference"
    echo "=== ${stack}: $(($(date +%s) - t0))s"
    mkdir -p "parity/${stack}"
    for d in build/tmp*/stamps; do
      [ -d "${d}" ] || continue
      d=${d%/stamps}
      mv "${d}/stamps" "parity/${stack}/${d#build/}"
    done
    [ -n "$(ls -A "parity/${stack}" 2>/dev/null)" ] || die "the ${stack} stack wrote no signatures"
  done
}

compare() {
  local build
  build=$(build_dir "${1:-}")
  [ -d "${build}/parity/feed" ] && [ -d "${build}/parity/scan" ] || die "no dumps in ${build}/parity; run dump first"
  python3 "${REPO}/scripts/feed-scan-parity.py" compare "${build}/parity"
}

explain() {
  local build
  build=$(build_dir "${1:-}")
  python3 "${REPO}/scripts/feed-scan-parity.py" explain --bitbake "${build}/bitbake" "${build}/parity" \
    || echo "feed-scan-parity: explain failed; the verdict comes from compare alone"
  return 0
}

case "${1:-}" in
  dump)
    shift
    dump "$@"
    ;;
  compare)
    shift
    compare "$@"
    ;;
  explain)
    shift
    explain "$@"
    ;;
  *) die "usage: $0 dump <machine> [build-dir] | compare [build-dir] | explain [build-dir]" ;;
esac
