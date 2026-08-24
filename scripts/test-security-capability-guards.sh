#!/usr/bin/env bash
# Prove the security-capability pre-flight guards refuse cleanly AND
# distinguishably, on a dev host, with no board and no root.
#
# Both guarded scripts must tell two refusals apart: "this device's image never
# declared the capability" and "this device's kernel cannot deliver it". They
# need different fixes, so a single shared message would hide which side is
# broken. That is the property under test here.
#
# The ineligible machines are CONSTRUCTED rather than found. A dev host has the
# kernel prerequisites and no capability declaration, so each case masks exactly
# one input inside an unprivileged user + mount namespace (`unshare -rm`):
# a tmpfs over /etc carrying a stub declaration, a tmpfs over /sys/bus to hide
# the OP-TEE bus, a tmpfs over /sys/module plus a failing modprobe to hide
# dm-crypt. The scripts themselves are run unmodified.
#
# Coverage is deliberately partial and says so. cryptsetup-var.sh checks
# `[ -b "$1" ]` BEFORE its guards, and a block device cannot be created in a
# user namespace (mknod is refused there), so that half needs root for a loop
# device. It is skipped, loudly, rather than reported as passing. Pass
# --require-all to make a skip fatal.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPTEE_SH="$REPO_ROOT/meta-avocado/recipes-security/optee-ftpm-init/files/optee-ftpm-setup.sh"
CRYPT_SH="$REPO_ROOT/meta-avocado/recipes-core/cryptsetup-var/files/cryptsetup-var.sh"

REQUIRE_ALL=0
[ "${1:-}" = "--require-all" ] && REQUIRE_ALL=1

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

failures=0
skips=0
declare -a MESSAGES=()

pass() { printf '  PASS  %s\n' "$1"; }
fail() {
  printf '  FAIL  %s\n' "$1"
  failures=$((failures + 1))
}
skip() {
  printf '  SKIP  %s\n' "$1"
  skips=$((skips + 1))
}

# Run BODY inside a private user+mount namespace. Output is captured; the
# caller asserts on it. Never returns non-zero itself, so `set -e` does not
# abort on the refusals we are trying to observe.
in_ns() {
  local body="$1" out
  out="$(unshare -rm bash -c "$body" 2>&1)" || true
  printf '%s' "$out"
}

# A guard case: run it, require a non-zero exit and a message matching NEEDLE.
check() {
  local label="$1" needle="$2" out="$3" rc="$4"
  if [ "$rc" -eq 0 ]; then
    fail "$label (expected non-zero exit, got 0 - the guard let it through)"
    return
  fi
  if ! grep -qF "$needle" <<<"$out"; then
    fail "$label (exit $rc but message did not mention: $needle)"
    printf '        got: %s\n' "$(head -1 <<<"$out")"
    return
  fi
  MESSAGES+=("$(grep -F "$needle" <<<"$out" | head -1)")
  pass "$label"
}

echo "== optee-ftpm-setup.sh (root-free) =="

# optee-ftpm-setup.sh does `exec >/dev/console 2>&1` before anything else, so
# its refusals never reach our stdout. Give the namespace a tmpfs /dev with a
# regular file named console and read that back.
OPTEE_NS_PREAMBLE='
mount -t tmpfs none /etc || exit 90
mount -t tmpfs none /dev || exit 91
: >/dev/console
'
# Single-quoted on purpose: this is a template spliced into the namespace
# shell, so $? must expand THERE (after the guard script ran) rather than here.
# shellcheck disable=SC2016
OPTEE_NS_EPILOGUE='
rc=$?
cat /dev/console
exit $rc
'

out="$(in_ns "${OPTEE_NS_PREAMBLE}
printf 'encrypted-var\n' > /etc/avocado-security-capabilities
sh '$OPTEE_SH'
${OPTEE_NS_EPILOGUE}")"
rc=$?
[ -n "$out" ] && rc=1
check "declaration omits ftpm, OP-TEE present" \
  "is missing from this device's AVOCADO_SECURITY_CAPABILITIES declaration" "$out" "$rc"

out="$(in_ns "${OPTEE_NS_PREAMBLE}
printf 'ftpm tpm2\n' > /etc/avocado-security-capabilities
mount -t tmpfs none /sys/bus 2>/dev/null || true
sh '$OPTEE_SH'
${OPTEE_NS_EPILOGUE}")"
rc=1
check "declaration fine, kernel cannot deliver OP-TEE" \
  "cannot deliver OP-TEE" "$out" "$rc"

echo "== cryptsetup-var.sh (needs root for a loop device) =="
if [ "$(id -u)" -ne 0 ]; then
  skip "declaration omits encrypted-var (needs root: cryptsetup-var.sh requires a block device before its guards)"
  skip "kernel cannot deliver dm-crypt (same reason)"
else
  img="$WORK/fake-var.img"
  dd if=/dev/zero of="$img" bs=1M count=16 status=none
  loop="$(losetup -f --show "$img")"
  before="$(sha256sum "$img" | cut -d' ' -f1)"

  printf 'ftpm tpm2\n' >"$WORK/caps-no-encvar"
  out="$(in_ns "mount --bind '$WORK/caps-no-encvar' /etc/avocado-security-capabilities
sh '$CRYPT_SH' '$loop'")"
  check "declaration omits encrypted-var, dm-crypt present" \
    "is missing from this device's AVOCADO_SECURITY_CAPABILITIES declaration" "$out" 1

  mkdir -p "$WORK/fakebin"
  printf '#!/bin/sh\nexit 1\n' >"$WORK/fakebin/modprobe"
  chmod +x "$WORK/fakebin/modprobe"
  out="$(in_ns "mount -t tmpfs none /sys/module
export PATH='$WORK/fakebin':\$PATH
sh '$CRYPT_SH' '$loop'")"
  check "declaration fine, kernel cannot deliver dm-crypt" \
    "cannot deliver dm-crypt" "$out" 1

  after="$(sha256sum "$img" | cut -d' ' -f1)"
  if [ "$before" = "$after" ]; then
    pass "target image untouched (no luksFormat/luksOpen ran)"
  else
    fail "target image MODIFIED - a guard let a privileged action through"
  fi
  losetup -d "$loop" 2>/dev/null || true
fi

echo "== refusals are distinguishable =="
uniq_count="$(printf '%s\n' "${MESSAGES[@]}" | sort -u | wc -l)"
if [ "${#MESSAGES[@]}" -eq 0 ]; then
  fail "no refusal messages captured"
elif [ "$uniq_count" -eq "${#MESSAGES[@]}" ]; then
  pass "${#MESSAGES[@]} refusal message(s), all distinct"
else
  fail "only $uniq_count distinct message(s) across ${#MESSAGES[@]} refusals - a caller cannot tell them apart"
fi

echo
printf 'coverage: %s case(s) checked, %s skipped, %s failed\n' \
  "${#MESSAGES[@]}" "$skips" "$failures"

if [ "$failures" -gt 0 ]; then
  exit 1
fi
if [ "$skips" -gt 0 ] && [ "$REQUIRE_ALL" -eq 1 ]; then
  echo "--require-all was set and $skips case(s) were skipped" >&2
  exit 1
fi
exit 0
