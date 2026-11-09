#!/usr/bin/env bash

# Standalone test for the Intel x86 /var LUKS key provider.
#
# Runs on any host with openssl 3.x (the same KDF the initramfs uses). The
# provider reads /sys/class/dmi/id/product_uuid and /sys/class/block, so the
# harness copies it and rewrites those two paths to a fixture tree.
#
# What matters most: an AMI placeholder product_uuid (the same on every unit)
# must never be the whole identity, or the fleet shares one /var key.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
provider="$here/../files/var-key.sh"

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

command -v openssl >/dev/null 2>&1 || {
  echo "SKIP: host missing openssl"
  exit 0
}
if ! openssl kdf -binary -keylen 8 -kdfopt pass:x -kdfopt salt:0123456789abcdef \
  -kdfopt iter:3 -kdfopt memcost:65536 -kdfopt lanes:1 ARGON2ID >/dev/null 2>&1; then
  echo "SKIP: host openssl has no ARGON2ID"
  exit 0
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fx="$work/sys"
mkdir -p "$fx/dmi" "$fx/devices/mmcblk0/mmcblk0p6" "$fx/devices/mmcblk0/device" "$fx/class/block" "$work/dev"
ln -s ../../devices/mmcblk0/mmcblk0p6 "$fx/class/block/mmcblk0p6"
touch "$work/dev/mmcblk0p6"
part="$work/dev/mmcblk0p6"
under_test="$work/var-key.sh"
sed -e "s|/sys/class/dmi/id/product_uuid|$fx/dmi/product_uuid|g" \
  -e "s|/sys/class/block/|$fx/class/block/|g" \
  "$provider" >"$under_test"
chmod +x "$under_test"
cid="$fx/devices/mmcblk0/device/cid"
uuid="$fx/dmi/product_uuid"

# --- Case 1: the eMMC CID of the var disk derives exactly 64 raw bytes ---
printf '150100474a3634328a1c2b3d4e5f60c1\n' >"$cid"
if "$under_test" "$part" >"$work/k1" 2>"$work/e1"; then
  n=$(wc -c <"$work/k1")
  if [[ "$n" -eq 64 ]]; then
    ok "the var disk's CID derives 64 raw key bytes"
  else
    bad "expected 64 bytes, got $n"
  fi
else
  bad "provider failed on a valid CID: $(cat "$work/e1")"
fi

# --- Case 2: deterministic ---
"$under_test" "$part" >"$work/k1b" 2>/dev/null || true
if cmp -s "$work/k1" "$work/k1b"; then
  ok "the same disk derives the same key every run"
else
  bad "not deterministic"
fi

# --- Case 3: another chip, another key ---
printf '150100474a3634328a1c2b3d4e5f60c2\n' >"$cid"
"$under_test" "$part" >"$work/k2" 2>/dev/null || true
if cmp -s "$work/k1" "$work/k2"; then
  bad "two CIDs derived the same key"
else
  ok "a different CID derives a different key"
fi

# --- Case 4: the AMI placeholder UUID is ignored, not mixed in ---
printf '150100474a3634328a1c2b3d4e5f60c1\n' >"$cid"
printf '03000200-0400-0500-0006-000700080009' >"$uuid"
"$under_test" "$part" >"$work/k3" 2>/dev/null || true
if cmp -s "$work/k1" "$work/k3"; then
  ok "the AMI placeholder product_uuid is ignored"
else
  bad "the placeholder UUID changed the key"
fi

# --- Case 5: placeholder UUID and no disk serial is a refusal ---
rm -f "$cid"
if "$under_test" "$part" >"$work/k4" 2>"$work/e4"; then
  bad "emitted a key from the AMI placeholder UUID alone (fleet-wide key)"
else
  if grep -qi 'refus' "$work/e4"; then
    ok "placeholder UUID alone is refused"
  else
    bad "refused without saying why: $(cat "$work/e4")"
  fi
fi

# --- Case 6: a real UUID alone still works (a disk without a readable serial) ---
printf '4c4c4544-0042-3510-8051-b4c04f4b4e32' >"$uuid"
if "$under_test" "$part" >"$work/k5" 2>"$work/e5"; then
  ok "a real product_uuid alone derives a key"
else
  bad "a real UUID was refused: $(cat "$work/e5")"
fi

echo
echo "passed: $pass  failed: $fail"
[[ "$fail" -eq 0 ]]
