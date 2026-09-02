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
      # keydb=match     enrolled db carries the certificate this image shipped
      # keydb=mismatch  enrolled db carries a DIFFERENT certificate
      # keydb=noref     enrolled db present, but no reference hash installed
      #
      # The db variable is 48 bytes of prefix (4 efivarfs attributes, a 28-byte
      # EFI_SIGNATURE_LIST header, a 16-byte SignatureOwner GUID) then the DER.
      # The reporter compares from byte 49 on, so the prefix content is
      # irrelevant here and only its LENGTH has to be right.
      keydb=*)
        mkdir -p "$root/sys/firmware/efi/efivars"
        local dbvar="$root/sys/firmware/efi/efivars/db-d719b2cb-3d3a-4596-a3bc-dad00e67656f"
        local payload="STAND-IN-FOR-A-DER-CERTIFICATE"
        : >"$dbvar"
        local i=0
        while [ "$i" -lt 48 ]; do
          printf '\000' >>"$dbvar"
          i=$((i + 1))
        done
        printf '%s' "$payload" >>"$dbvar"
        case "${opt#keydb=}" in
          match) printf '%s' "$payload" | sha256sum | awk '{print $1}' >"$root/db.der.sha256" ;;
          mismatch) printf '%s' "SOME-OTHER-CERTIFICATE" | sha256sum | awk '{print $1}' >"$root/db.der.sha256" ;;
          noref) ;;
          *)
            fail "unknown keydb mode: ${opt#keydb=}"
            return 1
            ;;
        esac
        ;;
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

# Substring form, for `detail`. Exact equality is wrong for that field on
# purpose: it carries the diagnostics of several independent probes joined
# together, so an exact-match assertion would have to spell out every message
# that happened to fire and would break whenever an unrelated probe gained one.
# What must hold is that a given probe's message is PRESENT - the property that
# was silently false while the field was assigned rather than appended.
expect_has() {
  local label="$1" root="$2" field="$3" want="$4"
  local out got
  out="$(sh "$root/report.sh" 2>/dev/null)" || {
    fail "$label (reporter exited non-zero)"
    return
  }
  got="$(printf '%s\n' "$out" | sed -n "s/^${field}=//p")"
  case "$got" in
    *"$want"*) pass "$label" ;;
    *) fail "$label (${field}=${got}, wanted it to contain ${want})" ;;
  esac
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

# The descriptor is PARSED, not sourced, so it can introduce no name into the
# reporter at all. This case predates that change - when the descriptor was
# sourced it could redefine read_rot_evidence outright - and is kept because the
# property it asserts must hold under either mechanism.
# rot_state is the one that must not be settable that way.
r="$(fixture secureboot=1 'store=rot_state="authenticated"')"
expect "a descriptor cannot assign rot_state authenticated" "$r" rot_state unauthenticated

printf '\n== keydb_origin ==\n'
r="$(fixture secureboot=1)"
expect "no store descriptor reports unknown" "$r" keydb_origin unknown

r="$(fixture secureboot=1 'store=store_trust="firmware-owned"')"
expect "a descriptor with no provenance line reports unknown" "$r" keydb_origin unknown
expect "that descriptor still carries its store_trust" "$r" store_trust firmware-owned

# firmware-resident is the descriptor's strongest claim, so it is the one the
# reporter refuses to take on the descriptor's word. These four cases are the
# whole contract: the claim is honoured only when the enrolled db demonstrably
# carries the certificate this image shipped.
#
# The previous version of this file asserted the opposite - that a descriptor
# claiming firmware-resident reports it - and so locked in the behaviour that a
# single write to an unverified rootfs could forge the provenance field.
r="$(fixture secureboot=1 keydb=match 'store=keydb_origin="firmware-resident"')"
expect "a corroborated firmware-resident claim is honoured" "$r" keydb_origin firmware-resident

r="$(fixture secureboot=1 keydb=mismatch 'store=keydb_origin="firmware-resident"')"
expect "an enrolled db that is not ours refuses the claim" "$r" keydb_origin unknown

r="$(fixture secureboot=1 keydb=noref 'store=keydb_origin="firmware-resident"')"
expect "no reference hash means the claim cannot be earned" "$r" keydb_origin unknown

r="$(fixture secureboot=1 'store=keydb_origin="firmware-resident"')"
expect "no enrolled db at all refuses the claim" "$r" keydb_origin unknown

r="$(fixture secureboot=1 'store=keydb_origin="runtime-mutable"')"
expect "a descriptor claiming runtime-mutable reports it" "$r" keydb_origin runtime-mutable

r="$(fixture secureboot=1 'store=keydb_origin="whatever"')"
expect "an unrecognised provenance falls back to unknown" "$r" keydb_origin unknown

r="$(fixture secureboot=1 'store=keydb_origin=""')"
expect "an empty provenance falls back to unknown" "$r" keydb_origin unknown

printf '\n== detail ==\n'

# The case that was silently broken. A board whose descriptor claims a
# firmware-resident key database it cannot corroborate has TWO things to say,
# and `rot_state=unauthenticated` is true on every board this ships to - so the
# root-of-trust message fired on every boot and erased the corroboration
# failure. The record then read `keydb_origin=unknown` with a detail about
# hardware attestation, which points a reader at the wrong subsystem entirely.
r="$(fixture secureboot=1 keydb=mismatch 'store=keydb_origin="firmware-resident"')"
expect_has "a refused keydb claim keeps its own explanation" "$r" \
  detail "does not contain the certificate this image shipped"
expect_has "and the root-of-trust message is still there beside it" "$r" \
  detail "no hardware attestation"

# One key per line is the record's whole format, so a joined detail must not
# introduce a newline - a consumer splitting on it would read the second half as
# a malformed field rather than as part of this one.
n="$(sh "$r/report.sh" 2>/dev/null | grep -c '^detail=')"
m="$(sh "$r/report.sh" 2>/dev/null | wc -l)"
if [ "$n" -eq 1 ] && [ "$m" -eq 5 ]; then
  pass "a joined detail stays on one line"
else
  fail "record has $m lines and $n detail lines, wanted 5 and 1"
fi

# The sentinel is REPLACED by the first real message, never accumulated onto.
# Appending to it would prefix every diagnosed board's detail with a claim that
# no probe ran, which contradicts the message immediately following it.
#
# The sentinel itself is unreachable on any real path - the enforcement branch
# writes on all four of its failure routes, and `read_rot_evidence` returns one
# of three values that all write - so it is a defensive default rather than an
# outcome. What is testable, and what these two cases cover, is that it never
# survives INTO a message.
for c in efivars-unmounted secureboot=0; do
  r="$(fixture $c)"
  out="$(sh "$r/report.sh" 2>/dev/null | sed -n 's/^detail=//p')"
  case "$out" in
    "no probe ran"*) fail "the sentinel leaked into a real detail ($c): $out" ;;
    *) pass "the sentinel does not survive into a real detail ($c)" ;;
  esac
done

r="$(fixture efivars-unmounted)"
expect "the first real message replaces the sentinel outright" "$r" \
  detail "efivarfs directory present but not mounted - no variables are readable"

printf '\n'
if [ "$failures" -ne 0 ]; then
  printf '%d check(s) failed\n' "$failures"
  exit 1
fi
printf 'all checks passed\n'
