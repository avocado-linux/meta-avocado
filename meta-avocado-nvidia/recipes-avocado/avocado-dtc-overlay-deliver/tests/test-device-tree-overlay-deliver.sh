#!/usr/bin/env bash

# Standalone test for the NVIDIA (Tegra) device-tree overlay delivery hook.
# Runs on any host with python3, jq, dtc and fdtoverlay. Feeds the hook a
# staged manifest and a fake stone manifest, then checks the emitted fragment,
# the merged DTB, and the claimed_by annotations. Not packaged into the recipe.
#
# Delivery on Tegra is a MERGED DTB published as
# .storage_devices.rootdisk.images.dtb, not a list of .dtbo files. The
# provisioning script reads that key at stone-provision-tegraflash.sh:43 and
# copies it to kernel_<basename>.dtb at :261-265, which is the file the flash
# writes to the kernel-dtb partition.
#
# Three properties are worth testing explicitly because each fails silently:
#
#   1. An unmerged base DTB published as images.dtb produces a board that boots
#      perfectly with no overlay applied. The merge tests below are the guard.
#   2. The destination is NOT discovered; the consumer reads a hardcoded
#      rootdisk. The drift test is the guard on that coupling.
#   3. tegraflash.overlays is advisory (:275-285 only warns on a missing file),
#      so it is checked as provenance, never as the delivery mechanism.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
hook="$here/../files/device-tree-overlay-deliver"

pass=0
fail=0
ok()  { printf '  ok   - %s\n' "$1"; pass=$((pass + 1)); }
bad() { printf '  FAIL - %s\n' "$1"; fail=$((fail + 1)); }

for t in python3 jq dtc fdtoverlay; do
    command -v "$t" >/dev/null 2>&1 || { echo "SKIP: host missing $t"; exit 0; }
done
[[ -x "$hook" ]] || { echo "FAIL - hook not executable: $hook"; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

bsp="$work/tegraflash-bsp"
mkdir -p "$bsp"

# A base DTB with __symbols__ so label-target overlays bind, matching the real
# L4T DTB (task 1.3 recorded SYMBOLS: present).
cat > "$work/base.dts" <<'EOF'
/dts-v1/;
/ {
    compatible = "nvidia,p3768-0000+p3767-0005";
    #address-cells = <1>;
    #size-cells = <1>;
    target_node: target-node {
        existing = "yes";
    };
};
EOF
# A real BSP ships one base DTB per module SKU - five of them on the Orin Nano
# devkit (p3767-0000/0001/0003/0004/0005). Picking by uniqueness is therefore
# not an option; the flash picks by DTBFILE, and so must the hook.
for sku in 0000 0003 0005; do
    dtc -@ -I dts -O dtb -o "$bsp/kernel_tegra234-test-$sku.dtb" "$work/base.dts" 2>/dev/null
    cp "$bsp/kernel_tegra234-test-$sku.dtb" "$bsp/tegra234-test-$sku.dtb"
done

# initrd-flash.sh:922 substitutes the flash XML's DTB_FILE with kernel_$DTBFILE,
# sourcing DTBFILE from this file. It is the only thing in the BSP that names
# which SKU's tree this machine actually boots.
write_env() {
    printf 'BOOTDEV="mmcblk0p1"\nDTBFILE="%s"\nROOTFS_DEVICE="mmcblk0"\n' "$1" \
        > "$bsp/.env.initrd-flash"
}
write_env "tegra234-test-0005.dtb"

# Overlay fixtures, each adding an identifiable property to the same target.
make_dtbo() {
    local out="$1" prop="$2"
    cat > "$work/$prop.dts" <<EOF
/dts-v1/;
/plugin/;
&target_node {
    $prop = "present";
};
EOF
    dtc -@ -I dts -O dtb -o "$out" "$work/$prop.dts" 2>/dev/null
}

make_staging() {
    local dir="$1"; shift
    mkdir -p "$dir"
    local entries=()
    for name in "$@"; do
        make_dtbo "$dir/$name.dtbo" "$name"
        entries+=("{\"name\": \"$name\", \"file\": \"$name.dtbo\", \"params\": {}, \"claimed_by\": null}")
    done
    local joined
    joined="$(IFS=,; echo "${entries[*]}")"
    printf '{"version": 1, "overlays": [%s]}\n' "$joined" > "$dir/overlays.manifest.json"
}

write_stone() {
    cat > "$1" <<EOF
{
  "runtime": {"platform": "avocado-jetson-orin-nano"},
  "storage_devices": {
    "rootdisk": {
      "images": {
        "rootfs": "rootfs.erofs",
        "tegraflash_bsp": "tegraflash-bsp"
      }
    }
  }
}
EOF
}
write_stone "$work/stone.json"

run_hook() {
    local staging="$1" stone="$2" fragment="$3"
    AVOCADO_DTBO_STAGING="$staging" \
    AVOCADO_OVERLAYS_MANIFEST="$staging/overlays.manifest.json" \
    AVOCADO_DELIVERY_FRAGMENT="$fragment" \
    AVOCADO_STONE_MANIFEST="$stone" \
    AVOCADO_STONE_DATA_DIR="$work" \
        "$hook"
}

# --- 1. a single overlay is merged, published and claimed --------------------
make_staging "$work/s1" alpha
if run_hook "$work/s1" "$work/stone.json" "$work/f1.json" >/dev/null 2>"$work/e1"; then
    dtb_rel="$(jq -r '.storage_devices.rootdisk.images.dtb // empty' "$work/f1.json")"
    if [[ -n "$dtb_rel" ]]; then
        ok "fragment publishes images.dtb"
    else
        bad "fragment has no images.dtb: $(jq -c . "$work/f1.json")"
    fi

    merged="$work/$dtb_rel"
    [[ -f "$merged" ]] || merged="$work/s1/$(basename "$dtb_rel")"
    if [[ -f "$merged" ]] && dtc -I dtb -O dts "$merged" 2>/dev/null | grep -q 'alpha = "present"'; then
        ok "the overlay is actually merged into the published DTB"
    else
        bad "published DTB does not carry the overlay property (unmerged base?)"
    fi

    claimed="$(jq -r '.overlays[0].claimed_by' "$work/s1/overlays.manifest.json")"
    if [[ "$claimed" == "avocado-jetson-orin-nano" ]]; then
        ok "overlay is marked claimed_by the platform"
    else
        bad "claimed_by not set (got '$claimed')"
    fi

    # Provenance list, not the delivery mechanism.
    if jq -e '.storage_devices.rootdisk.tegraflash.overlays | index("alpha.dtbo")' "$work/f1.json" >/dev/null; then
        ok "tegraflash.overlays records the delivered filename"
    else
        bad "tegraflash.overlays provenance missing: $(jq -c '.storage_devices.rootdisk.tegraflash' "$work/f1.json")"
    fi
else
    bad "hook failed on valid single-overlay input: $(cat "$work/e1")"
fi

# --- 2. two overlays both land, in declared order ---------------------------
make_staging "$work/s2" first second
if run_hook "$work/s2" "$work/stone.json" "$work/f2.json" >/dev/null 2>"$work/e2"; then
    dtb_rel="$(jq -r '.storage_devices.rootdisk.images.dtb' "$work/f2.json")"
    merged="$work/$dtb_rel"
    [[ -f "$merged" ]] || merged="$work/s2/$(basename "$dtb_rel")"
    decompiled="$(dtc -I dtb -O dts "$merged" 2>/dev/null || true)"
    if grep -q 'first = "present"' <<<"$decompiled" && grep -q 'second = "present"' <<<"$decompiled"; then
        ok "both overlays are merged into the published DTB"
    else
        bad "not all overlays merged"
    fi
    order="$(jq -r '.storage_devices.rootdisk.tegraflash.overlays | join(",")' "$work/f2.json")"
    if [[ "$order" == "first.dtbo,second.dtbo" ]]; then
        ok "declared overlay order is preserved"
    else
        bad "order not preserved: $order"
    fi
else
    bad "hook failed on two-overlay input: $(cat "$work/e2")"
fi

# --- 3. a broken overlay is a hard error, never an unmerged pass-through -----
# This is the failure that would otherwise ship a booting board with no overlay.
mkdir -p "$work/s3"
printf 'not a device tree blob' > "$work/s3/broken.dtbo"
cat > "$work/s3/overlays.manifest.json" <<'EOF'
{"version": 1, "overlays": [{"name": "broken", "file": "broken.dtbo", "params": {}, "claimed_by": null}]}
EOF
if run_hook "$work/s3" "$work/stone.json" "$work/f3.json" >/dev/null 2>"$work/e3"; then
    bad "hook accepted an unmergeable overlay (would publish an unmerged DTB)"
else
    if grep -qi "fdtoverlay\|merge" "$work/e3"; then
        ok "an fdtoverlay failure is a hard error"
    else
        bad "merge failure had no clear message: $(cat "$work/e3")"
    fi
fi

# --- 4a. the SKU named by DTBFILE is the one merged -------------------------
# The decisive case: several base DTBs are present and only one is the tree this
# machine boots. Merging into the wrong one produces a board that boots the
# untouched DTB with no overlay applied, reporting nothing.
make_staging "$work/s4a" alpha
if run_hook "$work/s4a" "$work/stone.json" "$work/f4a.json" >/dev/null 2>"$work/e4a"; then
    picked="$(jq -r '.storage_devices.rootdisk.images.dtb' "$work/f4a.json")"
    # Deliberately WITHOUT the kernel_ prefix. tegra-flash-helper.sh:567-572 does
    # `rm -f kernel_$base` then recreates it from the un-prefixed $base, so a
    # merged DTB published as kernel_<name> is deleted before it is ever read,
    # and the board boots the stock tree with no overlay and no error. Verified
    # on hardware 2026-08-15: kernel-dtb partitions p4/p7 contained a valid DTB
    # that did not carry the overlay marker.
    if [[ "$picked" == "tegra234-test-0005.dtb" ]]; then
        ok "images.dtb names the un-prefixed base DTB the signer reads"
    else
        bad "wrong name published (a kernel_ prefix here is deleted by the signer): $picked"
    fi
    if dtc -I dtb -O dts "$work/s4a/tegra234-test-0005.dtb" 2>/dev/null | grep -q 'alpha = "present"'; then
        ok "the overlay was merged into that SKU's tree"
    else
        bad "the selected tree carries no overlay"
    fi
    # The other SKUs must be left alone.
    if [[ ! -e "$work/s4a/tegra234-test-0000.dtb" ]]; then
        ok "unrelated SKU trees are not touched"
    else
        bad "hook staged a DTB for a SKU this machine does not boot"
    fi
else
    bad "hook failed with several base DTBs present: $(cat "$work/e4a")"
fi

# --- 4b. no DTBFILE selector is a hard error --------------------------------
mv "$bsp/.env.initrd-flash" "$work/stashed.env"
make_staging "$work/s4b" alpha
if run_hook "$work/s4b" "$work/stone.json" "$work/f4b.json" >/dev/null 2>"$work/e4b"; then
    bad "hook guessed a base DTB with no DTBFILE to select one"
else
    if grep -qiE "dtbfile|env.initrd-flash" "$work/e4b"; then
        ok "a missing DTBFILE selector is a hard error"
    else
        bad "missing-selector had no clear message: $(cat "$work/e4b")"
    fi
fi
mv "$work/stashed.env" "$bsp/.env.initrd-flash"

# --- 4c. a DTBFILE naming a file that is not there is a hard error ----------
write_env "tegra234-test-9999.dtb"
make_staging "$work/s4c" alpha
if run_hook "$work/s4c" "$work/stone.json" "$work/f4c.json" >/dev/null 2>"$work/e4c"; then
    bad "hook accepted a DTBFILE naming an absent DTB"
else
    if grep -qi "9999\|not found\|base dtb" "$work/e4c"; then
        ok "a DTBFILE naming an absent DTB is a hard error"
    else
        bad "absent-DTB case had no clear message: $(cat "$work/e4c")"
    fi
fi
write_env "tegra234-test-0005.dtb"

# --- 5. a missing rootdisk is a hard error ----------------------------------
cat > "$work/stone-nodisk.json" <<'EOF'
{"runtime": {"platform": "x"}, "storage_devices": {"otherdisk": {"images": {}}}}
EOF
make_staging "$work/s5" alpha
if run_hook "$work/s5" "$work/stone-nodisk.json" "$work/f5.json" >/dev/null 2>"$work/e5"; then
    bad "hook accepted a manifest with no rootdisk"
else
    if grep -qi "rootdisk" "$work/e5"; then
        ok "missing rootdisk is a hard error"
    else
        bad "no-rootdisk had no clear message: $(cat "$work/e5")"
    fi
fi

# --- 6. a DTB shadowing the merged one is a hard error ----------------------
# stone resolves images.dtb by name, first input dir wins. A same-named DTB
# beside the manifest would be picked over the merged copy in staging, shipping
# a tree with no overlays applied and reporting nothing.
make_staging "$work/s6" alpha
cp "$bsp/tegra234-test-0005.dtb" "$work/tegra234-test-0005.dtb"
if run_hook "$work/s6" "$work/stone.json" "$work/f6.json" >/dev/null 2>"$work/e6"; then
    bad "hook accepted a shadowing DTB beside the manifest"
else
    if grep -qi "shadow" "$work/e6"; then
        ok "a DTB that would shadow the merged one is a hard error"
    else
        bad "shadowing case had no clear message: $(cat "$work/e6")"
    fi
fi
rm -f "$work/tegra234-test-0005.dtb"

# --- 7. drift guard: hook target must match the consumer's read -------------
consumer="$here/../../../stone/tegra/stone-provision-tegraflash.sh"
if [[ -f "$consumer" ]]; then
    if grep -q '\.storage_devices\.rootdisk\.images\.dtb' "$consumer" \
        && jq -e '.storage_devices.rootdisk.images.dtb' "$work/f1.json" >/dev/null; then
        ok "hook writes the same path the provisioning script reads"
    else
        bad "hook target and consumer jq path have drifted apart"
    fi
else
    bad "consumer script not found at $consumer; drift guard cannot run"
fi

# --- 8. a malformed manifest entry fails clean, not with a traceback --------
# Every other bad input exits through die(); indexing a missing key would
# raise a bare KeyError instead. The distinction matters because the hook runs
# inside a build container, where a traceback is the least readable thing to
# land in the log.
make_staging "$work/s8" alpha
jq '.overlays[0] |= del(.file)' "$work/s8/overlays.manifest.json" > "$work/s8/m.json"
mv "$work/s8/m.json" "$work/s8/overlays.manifest.json"
if run_hook "$work/s8" "$work/stone.json" "$work/f8.json" >/dev/null 2>"$work/e8"; then
    bad "hook accepted an overlay entry with no 'file'"
elif grep -q "Traceback" "$work/e8"; then
    bad "malformed entry raised a traceback instead of a clean error: $(cat "$work/e8")"
elif grep -qi "file" "$work/e8"; then
    ok "a manifest entry missing 'file' fails clean"
else
    bad "malformed-entry case had no clear message: $(cat "$work/e8")"
fi

# --- 9. DTBFILE parsing tolerates ordinary shell forms ----------------------
# An unrecognised form matches nothing and falls through to the "no DTBFILE
# entry" die, which reports a MISSING selector when the truth is an unparsed
# one - pointing the reader at the wrong half of the system.
for form in 'export DTBFILE="tegra234-test-0005.dtb"' \
    'DTBFILE=tegra234-test-0005.dtb  # the SKU this board boots' \
    "DTBFILE='tegra234-test-0005.dtb'"; do
    printf 'BOOTDEV="mmcblk0p1"\n%s\nROOTFS_DEVICE="mmcblk0"\n' "$form" \
        > "$bsp/.env.initrd-flash"
    make_staging "$work/s9" alpha
    rm -f "$work/f9.json"
    if run_hook "$work/s9" "$work/stone.json" "$work/f9.json" >/dev/null 2>"$work/e9" \
        && [[ "$(jq -r '.storage_devices.rootdisk.images.dtb' "$work/f9.json")" \
            == "tegra234-test-0005.dtb" ]]; then
        ok "DTBFILE parsed from: $form"
    else
        bad "DTBFILE form not handled: $form :: $(cat "$work/e9")"
    fi
done
write_env "tegra234-test-0005.dtb"

echo
echo "passed: $pass  failed: $fail"
[[ "$fail" -eq 0 ]]
