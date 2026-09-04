#!/usr/bin/env bash

# Standalone test for the i.MX9 /var LUKS key provider.
#
# Runs on any host with openssl 3.x (the same KDF the initramfs uses). Cases 1
# to 6 copy the provider and rewrite its two sysfs paths to a fixture directory,
# leaving the logic under test (source precedence, the refusal, the KDF
# invocation) untouched. Case 7 instead runs the provider UNMODIFIED and passes
# the fixture root as its first argument, which is the path the build-time check
# in cryptsetup-var.bb uses; the rewrite cases cannot cover that, because they
# pass with the argument handling removed entirely.
#
# What matters most here is case 4: the provider must REFUSE rather than fall
# back to a constant, because a constant would give every board in the fleet the
# same /var key with no visible symptom.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
provider="$here/../files/var-key.sh"

pass=0
fail=0
ok()  { printf '  ok   - %s\n' "$1"; pass=$((pass + 1)); }
bad() { printf '  FAIL - %s\n' "$1"; fail=$((fail + 1)); }

command -v openssl >/dev/null 2>&1 || { echo "SKIP: host missing openssl"; exit 0; }
if ! openssl kdf -binary -keylen 8 -kdfopt pass:x -kdfopt salt:0123456789abcdef \
        -kdfopt iter:3 -kdfopt memcost:65536 -kdfopt lanes:1 ARGON2ID >/dev/null 2>&1; then
    echo "SKIP: host openssl has no ARGON2ID"
    exit 0
fi
[[ -f "$provider" ]] || { echo "FAIL - provider not found: $provider"; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Build a runnable copy whose sysfs constants point into the fixture tree.
fixture="$work/sys"
mkdir -p "$fixture/soc0" "$fixture/dt"
under_test="$work/var-key.sh"
sed -e "s|/sys/devices/soc0/serial_number|$fixture/soc0/serial_number|g" \
    -e "s|/sys/firmware/devicetree/base/serial-number|$fixture/dt/serial-number|g" \
    "$provider" > "$under_test"
chmod +x "$under_test"

# --- Case 1: a SoC UID yields exactly 64 raw bytes ---
printf '0123456789abcdeffedcba9876543210' > "$fixture/soc0/serial_number"
if "$under_test" > "$work/key1.bin" 2>"$work/key1.err"; then
    n=$(wc -c < "$work/key1.bin")
    if [[ "$n" -eq 64 ]]; then
        ok "SoC UID derives exactly 64 raw key bytes"
    else
        bad "expected 64 bytes, got $n"
    fi
else
    bad "provider failed on a valid SoC UID: $(cat "$work/key1.err")"
fi

# --- Case 2: derivation is deterministic (the same board unlocks every boot) ---
"$under_test" > "$work/key1b.bin" 2>/dev/null || true
if cmp -s "$work/key1.bin" "$work/key1b.bin"; then
    ok "the same SoC UID derives the same key on every run"
else
    bad "derivation is not deterministic - the volume would not reopen"
fi

# --- Case 3: a different board derives a different key (binding is real) ---
printf 'ffffffffffffffff0000000000000000' > "$fixture/soc0/serial_number"
"$under_test" > "$work/key2.bin" 2>/dev/null || true
if cmp -s "$work/key1.bin" "$work/key2.bin"; then
    bad "two different SoC UIDs derived the same key (no device binding)"
else
    ok "a different SoC UID derives a different key"
fi

# --- Case 4: no identity at all is a hard refusal, never a constant fallback ---
rm -f "$fixture/soc0/serial_number"
if "$under_test" > "$work/key3.bin" 2>"$work/key3.err"; then
    bad "provider emitted a key with no SoC UID (fleet-wide identical key)"
else
    if grep -qi 'refus\|device-unique' "$work/key3.err"; then
        ok "no SoC UID is refused rather than substituted with a constant"
    else
        bad "refused but without saying why: $(cat "$work/key3.err")"
    fi
fi

# --- Case 5: the DT serial-number is the documented secondary source ---
printf 'aaaabbbbccccddddeeeeffff00001111' > "$fixture/dt/serial-number"
if "$under_test" > "$work/key4.bin" 2>"$work/key4.err"; then
    n=$(wc -c < "$work/key4.bin")
    if [[ "$n" -eq 64 ]]; then
        ok "falls back to the DT serial-number when soc0 is absent"
    else
        bad "DT fallback produced $n bytes, expected 64"
    fi
else
    bad "DT fallback did not run: $(cat "$work/key4.err")"
fi

# --- Case 6: soc0 wins over the DT when both are present ---
printf '0123456789abcdeffedcba9876543210' > "$fixture/soc0/serial_number"
"$under_test" > "$work/key5.bin" 2>/dev/null || true
if cmp -s "$work/key1.bin" "$work/key5.bin"; then
    ok "soc0 takes precedence over the DT serial-number"
else
    bad "DT value won over soc0, or precedence changed"
fi

# --- Case 7: the optional first argument prefixes every identity read ---
# Runs the provider UNMODIFIED - no sed - which is what the build-time check in
# cryptsetup-var.bb does. Two different identities must give two different keys:
# a read that lost its "$ROOT" prefix resolves against this host's own /sys
# instead of the fixture and returns the same key both times, which is exactly
# the false pass the recipe's two-identity assertion exists to catch. Without
# this case the suite is green whether or not the prefixing works.
root_a="$work/root-a"
root_b="$work/root-b"
mkdir -p "$root_a/sys/devices/soc0" "$root_b/sys/devices/soc0"
printf '1111111111111111aaaaaaaaaaaaaaaa' > "$root_a/sys/devices/soc0/serial_number"
printf '2222222222222222bbbbbbbbbbbbbbbb' > "$root_b/sys/devices/soc0/serial_number"
if sh "$provider" "$root_a" > "$work/root_a.bin" 2>"$work/root_a.err" &&
    sh "$provider" "$root_b" > "$work/root_b.bin" 2>"$work/root_b.err"; then
    n=$(wc -c < "$work/root_a.bin")
    if [[ "$n" -ne 64 ]]; then
        bad "prefixed run produced $n bytes, expected 64"
    elif cmp -s "$work/root_a.bin" "$work/root_b.bin"; then
        bad "two different identities produced the same key - a read is not prefixed with \$ROOT"
    else
        ok "the first-argument prefix is honoured by every identity read"
    fi
else
    bad "provider refused under a first-argument fixture root: $(cat "$work/root_a.err" "$work/root_b.err")"
fi

# --- Case 8: the provider declares the identity paths the build check populates ---
# The build-time check builds its fixture from these lines; a read whose path is
# undeclared is never populated, so the branch is never exercised.
if grep -q '^# avocado-var-key-identity: /sys/devices/soc0/serial_number$' "$provider"; then
    ok "declares its primary identity source for the build-time check"
else
    bad "missing the avocado-var-key-identity declaration for soc0"
fi

# --- Case 9: a whitespace-only primary must not suppress a valid secondary ---
# `tr -d '\0\n'` strips NULs and newlines but leaves spaces and tabs, so a
# firmware field holding only blanks used to pass the -z test, be accepted as
# this board's identity, and stop the good DT serial from ever being read.
# Every board shipping that same blank field would derive one shared /var key.
ws_a="$work/ws-blank-primary"
ws_b="$work/ws-dt-only"
mkdir -p "$ws_a/sys/devices/soc0" "$ws_a/sys/firmware/devicetree/base"
mkdir -p "$ws_b/sys/firmware/devicetree/base"
printf '   \t  ' > "$ws_a/sys/devices/soc0/serial_number"
printf 'REAL-UNIQUE-SERIAL-42' > "$ws_a/sys/firmware/devicetree/base/serial-number"
printf 'REAL-UNIQUE-SERIAL-42' > "$ws_b/sys/firmware/devicetree/base/serial-number"
if sh "$provider" "$ws_a" > "$work/ws_a.bin" 2>"$work/ws_a.err" &&
    sh "$provider" "$ws_b" > "$work/ws_b.bin" 2>/dev/null; then
    if cmp -s "$work/ws_a.bin" "$work/ws_b.bin"; then
        ok "a whitespace-only soc0 falls through to the DT serial"
    else
        bad "a blank soc0 value still contributed to the derived key"
    fi
else
    bad "provider failed with a blank primary and a valid secondary: $(cat "$work/ws_a.err")"
fi

# --- Case 10: an all-whitespace identity everywhere is refused, not derived ---
ws_c="$work/ws-all-blank"
mkdir -p "$ws_c/sys/devices/soc0"
printf '  \t ' > "$ws_c/sys/devices/soc0/serial_number"
if sh "$provider" "$ws_c" > /dev/null 2>"$work/ws_c.err"; then
    bad "derived a key from an all-whitespace identity instead of refusing"
else
    ok "an all-whitespace identity is refused rather than substituted"
fi

# --- Case 11: one pinned identity derives one pinned key ---
# Every case above is a RELATIVE assertion: 64 bytes out, two identities
# differing, one identity repeating. All of them still hold after the KDF
# parameters change, because they change for both sides of the comparison. So
# an edit to iter, memcost, lanes, keylen or the salt derivation passes this
# suite while changing the /var key of every board already in the field.
#
# This vector is the suite's only absolute assertion, and it is what makes such
# an edit loud. It runs the provider UNMODIFIED through the argv fixture root,
# so it is pinned to the real derivation path rather than to a copy of the
# openssl invocation.
#
# If it fails after a deliberate provider change, the vector is NOT the thing
# to update first. A changed key means a board with an encrypted /var can no
# longer unlock it, so a migration has to land alongside: derive the old key,
# `luksAddKey` the new one, `luksKillSlot` the old. Re-pin only after that.
golden_id='AVOCADO-NXP-GOLDEN-VECTOR-0001'
golden_key='7f13ae56b31ee18afbd489e06f5f6c82fdc40299c7318b08defdd90ab648d394c588f6524e57266f0ec7bf136fb41bb4466c52e284c683a1845a22e7e97213d8'
gv="$work/golden"
mkdir -p "$gv/sys/devices/soc0"
printf '%s' "$golden_id" > "$gv/sys/devices/soc0/serial_number"
if sh "$provider" "$gv" > "$work/golden.bin" 2>"$work/golden.err"; then
    got="$(od -An -tx1 -v < "$work/golden.bin" | tr -d ' \n')"
    if [[ "$got" == "$golden_key" ]]; then
        ok "the pinned identity derives the pinned key"
    else
        bad "golden vector mismatch - the derivation changed, so every deployed board's /var key changed
         identity: $golden_id
         expected: $golden_key
         got:      $got"
    fi
else
    bad "provider refused the golden-vector identity: $(cat "$work/golden.err")"
fi

echo
echo "passed: $pass  failed: $fail"
[[ "$fail" -eq 0 ]]
