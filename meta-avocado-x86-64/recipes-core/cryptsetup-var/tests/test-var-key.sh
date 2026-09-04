#!/usr/bin/env bash

# Standalone test for the avocado-x86-64 /var LUKS key provider.
#
# Runs on any host with openssl 3.x (the same KDF the initramfs uses). Unlike
# the nxp and nvidia suites, which predate the argv contract and rewrite the
# provider's paths with sed, this one runs the provider UNMODIFIED and passes a
# fixture root as its first argument - the same path cryptsetup-var.bb's
# build-time check uses.
#
# The provider is not reachable from a build today: all three avocado-intel
# machines declare only tpm2, so nothing resolves it with encrypted-var set and
# the recipe's execution tier never runs against it. That is exactly why it
# needs a suite of its own - a regression here is otherwise caught by nothing
# until an Intel machine adds the capability.
#
# What matters most is case 4: DMI placeholder strings must not be treated as
# identities, and a placeholder in the FIRST source must not mask a usable
# value in the second. Whitebox and OEM boards ship these strings rather than
# leaving the field empty, so "non-empty" is not "unique", and a fleet that
# derived from one would share a single /var key with no visible symptom.

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

dmi="sys/class/dmi/id"

# Build a fixture root and run the unmodified provider against it. Passing "-"
# for a field leaves that file absent rather than empty, which is a different
# case: absent fails the [ -r ] test, empty passes it and yields "".
run_with() {
    local root="$1" uuid="$2" serial="$3"
    mkdir -p "$root/$dmi"
    [[ "$uuid"   == "-" ]] || printf '%s' "$uuid"   > "$root/$dmi/product_uuid"
    [[ "$serial" == "-" ]] || printf '%s' "$serial" > "$root/$dmi/product_serial"
    sh "$provider" "$root"
}

# --- Case 1: a unique product_uuid yields exactly 64 raw bytes ---
if run_with "$work/c1" "4c4c4544-0037-3010-8043-b4c04f565331" "-" \
        > "$work/key1.bin" 2>"$work/key1.err"; then
    n=$(wc -c < "$work/key1.bin")
    if [[ "$n" -eq 64 ]]; then
        ok "a unique product_uuid derives exactly 64 raw key bytes"
    else
        bad "expected 64 bytes, got $n"
    fi
else
    bad "provider failed on a valid product_uuid: $(cat "$work/key1.err")"
fi

# --- Case 2: a different identity derives a different key ---
# Exit status and length are asserted here too. Checking only "key2 != key1"
# passes a provider that exits non-zero, or emits nothing at all, since empty
# output also differs from key1.
if run_with "$work/c2" "11111111-2222-3333-4444-555555555555" "-" \
        > "$work/key2.bin" 2>"$work/key2.err"; then
    n=$(wc -c < "$work/key2.bin")
    if [[ "$n" -ne 64 ]]; then
        bad "second identity produced $n bytes, expected 64"
    elif cmp -s "$work/key1.bin" "$work/key2.bin"; then
        bad "two different UUIDs produced the same key - not device-unique"
    else
        ok "a different product_uuid derives a different key"
    fi
else
    bad "provider failed on a second valid UUID: $(cat "$work/key2.err")"
fi

# --- Case 3: product_serial is the documented secondary source ---
if run_with "$work/c3" "-" "SN-0123456789-UNIQUE" \
        > "$work/key3.bin" 2>"$work/key3.err"; then
    n=$(wc -c < "$work/key3.bin")
    if [[ "$n" -eq 64 ]]; then
        ok "falls back to product_serial when product_uuid is absent"
    else
        bad "product_serial fallback produced $n bytes, expected 64"
    fi
else
    bad "product_serial fallback did not run: $(cat "$work/key3.err")"
fi

# --- Case 4: a placeholder in product_uuid must not mask a usable serial ---
# The regression this suite exists for. Reading the first non-empty field and
# only then validating it means a board whose uuid carries an OEM placeholder
# is refused outright, even though its product_serial is perfectly unique.
if run_with "$work/c4" "00000000-0000-0000-0000-000000000000" "SN-0123456789-UNIQUE" \
        > "$work/key4.bin" 2>"$work/key4.err"; then
    if cmp -s "$work/key3.bin" "$work/key4.bin"; then
        ok "a placeholder product_uuid falls through to product_serial"
    else
        bad "derived a key, but not the one product_serial alone yields"
    fi
else
    bad "placeholder uuid masked a usable product_serial: $(cat "$work/key4.err")"
fi

# --- Case 5: placeholders in BOTH sources are refused, never substituted ---
if run_with "$work/c5" "Default string" "To Be Filled By O.E.M." \
        > "$work/key5.bin" 2>"$work/key5.err"; then
    bad "derived a key from placeholder DMI values instead of refusing"
else
    if grep -qi 'refus\|device-unique' "$work/key5.err"; then
        ok "placeholders in both sources are refused rather than substituted"
    else
        bad "refused but without saying why: $(cat "$work/key5.err")"
    fi
fi

# --- Case 6: no DMI at all is refused ---
if run_with "$work/c6" "-" "-" > "$work/key6.bin" 2>"$work/key6.err"; then
    bad "derived a key with no DMI identifier present"
else
    ok "an absent DMI identifier is refused"
fi

# --- Case 7: placeholder variants the denylist is not written for ---
# The regression this pins is subtle and was shipped once. Validating each
# source in turn (rather than taking the first non-empty and validating after)
# means a listed placeholder in product_uuid now falls THROUGH to
# product_serial - so the denylist has to be right for the serial too, where
# previously the short-circuit hid its gaps. Every value below is a real DMI
# string that differs from a listed one only by case or padding.
for variant in "To be filled by O.E.M." "default string" "0" "Default string " "DEFAULT STRING"; do
    root="$work/c7-$(printf '%s' "$variant" | tr -c 'a-zA-Z0-9' '_')"
    if run_with "$root" "00000000-0000-0000-0000-000000000000" "$variant" \
            > "$root.bin" 2>"$root.err"; then
        bad "derived a key from the placeholder variant '$variant'"
    else
        ok "refuses the placeholder variant '$variant'"
    fi
done

# --- Case 8: a usable uuid is not discarded because the serial is a placeholder ---
# The mirror of case 4. The first source wins when it is usable, and a
# placeholder further down the list must not disturb that.
if run_with "$work/c8" "4c4c4544-0037-3010-8043-b4c04f565331" "Default string" \
        > "$work/key8.bin" 2>"$work/key8.err"; then
    if cmp -s "$work/key1.bin" "$work/key8.bin"; then
        ok "a usable product_uuid wins over a placeholder product_serial"
    else
        bad "a placeholder serial changed the key derived from a usable uuid"
    fi
else
    bad "a placeholder serial masked a usable uuid: $(cat "$work/key8.err")"
fi

# Not covered, deliberately: the `tr -d '\0\n'` normalisation on the identity
# read. It cannot be observed from outside the provider, so no case here can
# fail when it is removed, and a case that cannot fail is false confidence
# rather than coverage. A trailing newline is stripped by `$(...)` itself
# whether or not the provider normalises, and a NUL cannot survive command
# substitution in any of the shells this runs under. Replacing the read with a
# plain `cat "$f"` leaves this whole suite green - checked, not assumed. The
# normalisation stays because it is correct for the device-tree providers that
# share this shape, not because anything here proves it.

# --- Case 9: the provider declares its identity paths for the build check ---
for path in /sys/class/dmi/id/product_uuid /sys/class/dmi/id/product_serial; do
    if grep -q "^# avocado-var-key-identity: $path\$" "$provider"; then
        ok "declares $path for the build-time check"
    else
        bad "missing the avocado-var-key-identity declaration for $path"
    fi
done

# --- Case 10: one pinned identity derives one pinned key ---
# Every case above is a RELATIVE assertion: 64 bytes out, two identities
# differing, a placeholder refused. All of them still hold after the KDF
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
golden_id='AVOCADO-X86-GOLDEN-VECTOR-0001'
golden_key='d5c9fd6845692cfa1c5b95af02749020cd00a0d6c94cf2048da845c9c58ea1ba94f01aebe8f3a2c8f02ad07cf35e550c950bc84389c56997a4931fb8e5c77244'
gv="$work/golden"
mkdir -p "$gv/sys/class/dmi/id"
printf '%s' "$golden_id" > "$gv/sys/class/dmi/id/product_uuid"
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
