#!/usr/bin/env bash

# Standalone test harness for the avocado-dtc-overlay SDK wrapper.
#
# Runs on any host with dtc + cpp + fdtget (the same tools the wrapper uses in
# the SDK). Exercises the wrapper against real .dtso inputs and asserts the
# observable output structure, so the build-correctness contract is verified
# without a full BitBake/SDK build. Not packaged into the recipe.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
wrapper="$here/../files/avocado-dtc-overlay"

pass=0
fail=0

ok()   { printf '  ok   - %s\n' "$1"; pass=$((pass + 1)); }
bad()  { printf '  FAIL - %s\n' "$1"; fail=$((fail + 1)); }

for t in dtc cpp fdtget; do
    command -v "$t" >/dev/null 2>&1 || { echo "SKIP: host missing $t"; exit 0; }
done

if [[ ! -x "$wrapper" ]]; then
    echo "FAIL - wrapper not found or not executable: $wrapper"
    exit 1
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Fake KDIR mirroring kernel-devsrc layout: a real dt-bindings header the
# wrapper's cpp include path must resolve.
kdir="$work/kernel"
mkdir -p "$kdir/include/dt-bindings/gpio" "$kdir/scripts/dtc/include-prefixes"
cat > "$kdir/include/dt-bindings/gpio/gpio.h" <<'EOF'
#ifndef _DT_BINDINGS_GPIO_GPIO_H
#define _DT_BINDINGS_GPIO_GPIO_H
#define GPIO_ACTIVE_HIGH 0
#define GPIO_ACTIVE_LOW  1
#endif
EOF
ln -s ../../../include/dt-bindings "$kdir/scripts/dtc/include-prefixes/dt-bindings"

run() { "$wrapper" --kdir "$kdir" "$@"; }

# --- Case 1: path-targeted, label-free overlay compiles cleanly ---
cat > "$work/path.dtso" <<'EOF'
/dts-v1/;
/plugin/;
/ {
    fragment@0 {
        target-path = "/";
        __overlay__ {
            acme-path-node {
                compatible = "acme,pathwidget";
            };
        };
    };
};
EOF
if run --src "$work/path.dtso" --out "$work/path.dtbo" >/dev/null 2>"$work/path.err"; then
    if fdtget -l "$work/path.dtbo" / 2>/dev/null | grep -q '^fragment@'; then
        ok "path-targeted label-free overlay builds (no false negative on absent __symbols__)"
    else
        bad "path overlay built but produced no fragment@ node"
    fi
else
    bad "path-targeted overlay rejected (regression: valid overlay); stderr: $(cat "$work/path.err")"
fi

# --- Case 2: dt-bindings include resolves + external phandle target -> __fixups__ ---
cat > "$work/phandle.dtso" <<'EOF'
/dts-v1/;
/plugin/;
#include <dt-bindings/gpio/gpio.h>
/ {
    fragment@0 {
        target = <&spi0>;
        __overlay__ {
            status = "okay";
            acme_dev: acme-device {
                compatible = "acme,widget";
                enable-gpios = <&gpio1 5 GPIO_ACTIVE_HIGH>;
            };
        };
    };
};
EOF
if run --src "$work/phandle.dtso" --out "$work/phandle.dtbo" >/dev/null 2>"$work/phandle.err"; then
    if fdtget -l "$work/phandle.dtbo" / 2>/dev/null | grep -q '^__fixups__$'; then
        ok "external-phandle overlay builds with dt-bindings include and exports __fixups__"
    else
        bad "phandle overlay built but __fixups__ missing"
    fi
else
    bad "phandle overlay with dt-bindings include rejected; stderr: $(cat "$work/phandle.err")"
fi

# --- Case 3: missing /plugin/; is a hard error (the #1 silent-failure) ---
cat > "$work/noplugin.dtso" <<'EOF'
/dts-v1/;
/ {
    acme-node {
        compatible = "acme,notanoverlay";
    };
};
EOF
if run --src "$work/noplugin.dtso" --out "$work/noplugin.dtbo" >/dev/null 2>"$work/noplugin.err"; then
    bad "overlay without /plugin/; was accepted (should hard-error)"
else
    if grep -qi 'plugin' "$work/noplugin.err"; then
        ok "missing /plugin/; hard-errors with a clear message"
    else
        bad "missing /plugin/; failed but message did not mention /plugin/;: $(cat "$work/noplugin.err")"
    fi
fi

# --- Case 4: missing/invalid KDIR is a hard error ---
if "$wrapper" --kdir "$work/nonexistent-kdir" --src "$work/path.dtso" \
        --out "$work/x.dtbo" >/dev/null 2>"$work/kdir.err"; then
    bad "invalid --kdir was accepted (should hard-error)"
else
    ok "invalid --kdir hard-errors"
fi

# --- Case 5: garbage source fails the dtc compile (not a silent pass) ---
printf 'this is not device tree source {{{\n' > "$work/garbage.dtso"
if run --src "$work/garbage.dtso" --out "$work/garbage.dtbo" >/dev/null 2>"$work/garbage.err"; then
    bad "malformed source was accepted (should fail compile)"
else
    ok "malformed source fails the build"
fi

# --- Case 6: $CROSS_COMPILE-prefixed preprocessor is used when set ---
# /usr/bin/cpp exists, so CROSS_COMPILE=/usr/bin/ resolves ${CROSS_COMPILE}cpp.
if CROSS_COMPILE="/usr/bin/" "$wrapper" --kdir "$kdir" --src "$work/path.dtso" \
        --out "$work/cross.dtbo" >/dev/null 2>"$work/cross.err"; then
    ok "\$CROSS_COMPILE-prefixed cpp resolves and builds"
else
    bad "\$CROSS_COMPILE resolution broke the build; stderr: $(cat "$work/cross.err")"
fi

echo
echo "passed: $pass  failed: $fail"
[[ "$fail" -eq 0 ]]
