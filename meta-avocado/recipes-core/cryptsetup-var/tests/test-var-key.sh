#!/usr/bin/env bash

# Standalone test for the shared /var LUKS key provider.
#
# Runs on any host with openssl 3.x (the KDF the initramfs uses). The provider
# reads absolute paths, so the harness copies it with those paths rewritten into
# a fixture directory; the logic under test is otherwise untouched.
#
# The provider must refuse rather than fall back to a constant (a constant would
# give every board the same /var key), must not need the /var secret that a
# first boot cannot have, and must derive the same key as the NXP provider for
# the same SoC UID.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
provider="$here/../files/var-key.sh"
nxp="$here/../../../../meta-avocado-nxp/recipes-core/cryptsetup-var/files/var-key.sh"

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

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
f="$work/fx"
mkdir -p "$f"
rewrite() {
    sed -e "s|/sys/devices/soc0/serial_number|$f/soc|g" \
        -e "s|/sys/firmware/devicetree/base/serial-number|$f/dt|g" \
        -e "s|/proc/cpuinfo|$f/cpuinfo|g" \
        -e "s|/var/private/var-key-secret|$f/secret|g" "$1" > "$2"
}
rewrite "$provider" "$work/vk.sh"

key() { sh "$work/vk.sh" 2>/dev/null | sha256sum | cut -c1-64; }
runs() { sh "$work/vk.sh" >/dev/null 2>&1; }
len() { sh "$work/vk.sh" 2>/dev/null | wc -c; }

if runs; then bad "no identifier: refuses"; else ok "no identifier: refuses"; fi

printf 'Serial\t\t: 0000000000000000\n' > "$f/cpuinfo"
if runs; then bad "all-zero cpuinfo serial: refuses"; else ok "all-zero cpuinfo serial: refuses"; fi

printf 'Serial\t\t: 10000000abcd1234\n' > "$f/cpuinfo"
[[ "$(len)" -eq 64 ]] && ok "cpuinfo serial: 64-byte key" || bad "cpuinfo serial: 64-byte key"
k_cpu="$(key)"

printf 'c0ffee1234567890\0' > "$f/dt"
k_dt="$(key)"
[[ "$k_dt" != "$k_cpu" ]] && ok "DT serial-number beats cpuinfo" || bad "DT serial-number beats cpuinfo"

printf 'deadbeef\n' > "$f/soc"
k_soc="$(key)"
[[ "$k_soc" != "$k_dt" ]] && ok "SoC UID beats DT serial-number" || bad "SoC UID beats DT serial-number"
[[ "$(key)" == "$k_soc" ]] && ok "deterministic" || bad "deterministic"

printf 's3cret' > "$f/secret"
[[ "$(key)" != "$k_soc" ]] && ok "a provisioned secret is mixed in" || bad "a provisioned secret is mixed in"
rm "$f/secret"

if [[ -f "$nxp" ]]; then
    rewrite "$nxp" "$work/nxp.sh"
    [[ "$(sh "$work/nxp.sh" 2>/dev/null | sha256sum | cut -c1-64)" == "$k_soc" ]] \
        && ok "same key as the NXP provider for the same SoC UID" \
        || bad "same key as the NXP provider for the same SoC UID"
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
