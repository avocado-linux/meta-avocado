#!/usr/bin/env bash
# Prove the boot-integrity reporter never publishes enforcement without what
# that enforcement is worth, and never reaches `authenticated` by default.
#
# Two properties are under test and they are the two that would be dangerous to
# get wrong. First, the single-emission invariant: exactly one printf at
# statement position, so every path emits all five fields or none. Second, the
# fail direction of the two indicators - `rot_state` reaches `authenticated`
# only on a source that was read AND parsed AND matched, and `keydb_origin`
# falls to `unknown` for every input that is not a recognised provenance.
#
# The reporter's paths are compile-time constants, so each case runs a COPY of
# the script whose constant assignments have been rewritten to point inside a
# fixture root. Only the five `NAME="/..."` lines are touched; every branch
# under test is the shipped code.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$REPO_ROOT/meta-avocado/recipes-core/boot-integrity/boot-integrity-report.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

failures=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() {
  printf '  FAIL  %s\n' "$1"
  failures=$((failures + 1))
}

# Build a fixture root and a reporter copy bound to it. Options, in any order:
#   secureboot=<byte>  install a SecureBoot efivar with that value, mounted
#   efivars-unmounted  create the efivars directory but leave it off /proc/mounts
#   rot=<text>         install an AHAB lifecycle source holding <text>
#   store=<lines>      install the store descriptor holding <lines>
fixture() {
  local root="$WORK/case$RANDOM$RANDOM"
  mkdir -p "$root/run" "$root/etc/avocado" "$root/rot"
  : >"$root/proc-mounts"

  local opt
  for opt in "$@"; do
    case "$opt" in
      secureboot=*)
        mkdir -p "$root/sys/firmware/efi/efivars"
        # A 4-byte attribute header then the value byte, as efivarfs presents it.
        local var="$root/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
        printf '\006\000\000\000' >"$var"
        printf '%b' "\\0$(printf '%03o' "${opt#secureboot=}")" >>"$var"
        printf 'efivarfs %s/sys/firmware/efi/efivars efivarfs rw 0 0\n' "$root" \
          >>"$root/proc-mounts"
        ;;
      efivars-unmounted) mkdir -p "$root/sys/firmware/efi/efivars" ;;
      rot=*) printf '%s\n' "${opt#rot=}" >"$root/rot/lifecycle" ;;
      store=*) printf '%s\n' "${opt#store=}" >"$root/etc/avocado/boot-integrity-store" ;;
      *)
        fail "unknown fixture option: $opt"
        return 1
        ;;
    esac
  done

  sed -e "s|^RECORD=\"/|RECORD=\"$root/|" \
    -e "s|^EFIVARS=\"/|EFIVARS=\"$root/|" \
    -e "s|^STORE_DESC=\"/|STORE_DESC=\"$root/|" \
    -e "s|^MOUNTS=\"/proc/mounts\"|MOUNTS=\"$root/proc-mounts\"|" \
    -e "s|^ROT_SOURCES=.*|ROT_SOURCES=\"$root/rot/lifecycle\"|" \
    "$SCRIPT" >"$root/report.sh"
  chmod +x "$root/report.sh"
  printf '%s' "$root"
}

# Run a fixture's reporter and assert one field. Also asserts, on every single
# case, that the record carries all five fields in order - that is the
# single-emission invariant, and it is worth re-checking per path rather than
# once, since the failure it guards against is path-specific.
expect() {
  local label="$1" root="$2" field="$3" want="$4"
  local out got
  out="$(sh "$root/report.sh" 2>/dev/null)" || {
    fail "$label (reporter exited non-zero)"
    return
  }

  local record_fields
  record_fields="$(sed -E 's/=.*//' "$root/run/avocado-boot-integrity" | paste -sd, -)"
  if [ "$record_fields" != "enforcement,rot_state,store_trust,keydb_origin,detail" ]; then
    fail "$label (record fields were '$record_fields')"
    return
  fi

  got="$(printf '%s\n' "$out" | sed -n "s/^${field}=//p")"
  if [ "$got" = "$want" ]; then
    pass "$label"
  else
    fail "$label (${field}=${got}, wanted ${want})"
  fi
}

printf '\n== single emission ==\n'
n="$(grep -cE '^[[:space:]]*printf ' "$SCRIPT")"
if [ "$n" -eq 1 ]; then
  pass "exactly one printf at statement position"
else
  fail "found $n printf statements, wanted 1"
fi

printf '\n== rot_state ==\n'
r="$(fixture)"
expect "no efivarfs at all reports rot_state unavailable" "$r" rot_state unavailable
expect "no efivarfs at all reports enforcement unavailable" "$r" enforcement unavailable

r="$(fixture efivars-unmounted)"
expect "efivarfs present but unmounted reports rot_state unavailable" "$r" rot_state unavailable

r="$(fixture secureboot=1)"
expect "enforcement enabled with no attestation source is unauthenticated" "$r" rot_state unauthenticated
expect "enforcement enabled is reported as enabled" "$r" enforcement enabled

r="$(fixture secureboot=0)"
expect "enforcement disabled is still unauthenticated, not unavailable" "$r" rot_state unauthenticated

r="$(fixture secureboot=1 "rot=OEM closed")"
expect "a parsed closed lifecycle reports authenticated" "$r" rot_state authenticated

r="$(fixture secureboot=1 "rot=OEM open")"
expect "a readable but unrecognised lifecycle is unauthenticated" "$r" rot_state unauthenticated

r="$(fixture secureboot=1 "rot=")"
expect "an empty lifecycle source is unauthenticated" "$r" rot_state unauthenticated

r="$(fixture "rot=OEM closed")"
expect "a closed lifecycle with no enforcement stays unavailable" "$r" rot_state unavailable

# The descriptor is sourced, so every name in the reporter is within its reach.
# rot_state is the one that must not be settable that way.
r="$(fixture secureboot=1 'store=rot_state="authenticated"')"
expect "a descriptor cannot assign rot_state authenticated" "$r" rot_state unauthenticated

printf '\n== keydb_origin ==\n'
r="$(fixture secureboot=1)"
expect "no store descriptor reports unknown" "$r" keydb_origin unknown

r="$(fixture secureboot=1 'store=store_trust="firmware-owned"')"
expect "a descriptor with no provenance line reports unknown" "$r" keydb_origin unknown
expect "that descriptor still carries its store_trust" "$r" store_trust firmware-owned

r="$(fixture secureboot=1 'store=keydb_origin="firmware-resident"')"
expect "a descriptor claiming firmware-resident reports it" "$r" keydb_origin firmware-resident

r="$(fixture secureboot=1 'store=keydb_origin="runtime-mutable"')"
expect "a descriptor claiming runtime-mutable reports it" "$r" keydb_origin runtime-mutable

r="$(fixture secureboot=1 'store=keydb_origin="whatever"')"
expect "an unrecognised provenance falls back to unknown" "$r" keydb_origin unknown

r="$(fixture secureboot=1 'store=keydb_origin=""')"
expect "an empty provenance falls back to unknown" "$r" keydb_origin unknown

printf '\n'
if [ "$failures" -ne 0 ]; then
  printf '%d check(s) failed\n' "$failures"
  exit 1
fi
printf 'all checks passed\n'
