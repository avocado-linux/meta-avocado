#!/usr/bin/env bash

# Standalone test for the Jetson /var LUKS key provider.
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

# --- Case 1: a DT serial-number yields exactly 64 raw bytes ---
printf '0123456789abcdeffedcba9876543210' > "$fixture/dt/serial-number"
if "$under_test" > "$work/key1.bin" 2>"$work/key1.err"; then
    n=$(wc -c < "$work/key1.bin")
    if [[ "$n" -eq 64 ]]; then
        ok "DT serial-number derives exactly 64 raw key bytes"
    else
        bad "expected 64 bytes, got $n"
    fi
else
    bad "provider failed on a valid serial: $(cat "$work/key1.err")"
fi

# --- Case 2: derivation is deterministic (the same board unlocks every boot) ---
"$under_test" > "$work/key1b.bin" 2>/dev/null || true
if cmp -s "$work/key1.bin" "$work/key1b.bin"; then
    ok "the same serial derives the same key on every run"
else
    bad "derivation is not deterministic - the volume would not reopen"
fi

# --- Case 3: a different board derives a different key (binding is real) ---
printf 'ffffffffffffffff0000000000000000' > "$fixture/dt/serial-number"
"$under_test" > "$work/key2.bin" 2>/dev/null || true
if cmp -s "$work/key1.bin" "$work/key2.bin"; then
    bad "two different serials derived the same key (no device binding)"
else
    ok "a different serial derives a different key"
fi

# --- Case 4: no identity at all is a hard refusal, never a constant fallback ---
rm -f "$fixture/dt/serial-number"
if "$under_test" > "$work/key3.bin" 2>"$work/key3.err"; then
    bad "provider emitted a key with no serial (fleet-wide identical key)"
else
    if grep -qi 'refus\|device-unique' "$work/key3.err"; then
        ok "no serial is refused rather than substituted with a constant"
    else
        bad "refused but without saying why: $(cat "$work/key3.err")"
    fi
fi

# --- Case 5: soc0 serial_number is the documented secondary source ---
printf 'aaaabbbbccccddddeeeeffff00001111' > "$fixture/soc0/serial_number"
if "$under_test" > "$work/key4.bin" 2>"$work/key4.err"; then
    n=$(wc -c < "$work/key4.bin")
    if [[ "$n" -eq 64 ]]; then
        ok "falls back to soc0 serial_number when the DT property is absent"
    else
        bad "soc0 fallback produced $n bytes, expected 64"
    fi
else
    bad "soc0 fallback did not run: $(cat "$work/key4.err")"
fi

# --- Case 6: the DT property wins over soc0 when both are present ---
printf '0123456789abcdeffedcba9876543210' > "$fixture/dt/serial-number"
"$under_test" > "$work/key5.bin" 2>/dev/null || true
if cmp -s "$work/key1.bin" "$work/key5.bin"; then
    ok "the DT serial-number takes precedence over soc0"
else
    bad "soc0 won over the DT property, or precedence changed"
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
mkdir -p "$root_a/sys/firmware/devicetree/base" "$root_b/sys/firmware/devicetree/base"
printf '1111111111111111aaaaaaaaaaaaaaaa' > "$root_a/sys/firmware/devicetree/base/serial-number"
printf '2222222222222222bbbbbbbbbbbbbbbb' > "$root_b/sys/firmware/devicetree/base/serial-number"
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
if grep -q '^# avocado-var-key-identity: /sys/firmware/devicetree/base/serial-number$' "$provider"; then
    ok "declares its primary identity source for the build-time check"
else
    bad "missing the avocado-var-key-identity declaration for the DT serial-number"
fi

echo
echo "passed: $pass  failed: $fail"
[[ "$fail" -eq 0 ]]
