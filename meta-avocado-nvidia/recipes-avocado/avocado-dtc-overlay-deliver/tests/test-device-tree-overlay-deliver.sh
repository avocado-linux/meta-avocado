#!/usr/bin/env bash

# Standalone test for the NVIDIA (Tegra) device-tree overlay delivery hook.
# Runs on any host with python3, jq, dtc and fdtoverlay. Feeds the hook a
# staged manifest and a fake stone manifest, then checks the emitted fragment,
# the merged DTB, and the claimed_by annotations. Not packaged into the recipe.
#
# Delivery on Tegra is a MERGED DTB published as
# .storage_devices.rootdisk.images.dtb, not a list of .dtbo files. The
# tegraflash engine reads that key (avocado_tegraflash/manifest.py) and stages
# it as <basename>.dtb and kernel_<basename>.dtb (staging.copy_images); the
# kernel_ copy is the file the flash writes to the kernel-dtb partition.
#
# Three properties are worth testing explicitly because each fails silently:
#
#   1. An unmerged base DTB published as images.dtb produces a board that boots
#      perfectly with no overlay applied. The merge tests below are the guard.
#   2. The destination is NOT discovered; the consumer reads a hardcoded
#      rootdisk. The drift test is the guard on that coupling.
#   3. tegraflash.overlays is advisory (staging.verify_overlays only warns on a missing file),
#      so it is checked as provenance, never as the delivery mechanism.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
hook="$here/../files/device-tree-overlay-deliver"

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

for t in python3 jq dtc fdtoverlay; do
  command -v "$t" >/dev/null 2>&1 || {
    echo "SKIP: host missing $t"
    exit 0
  }
done
[[ -x "$hook" ]] || {
  echo "FAIL - hook not executable: $hook"
  exit 1
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

bsp="$work/tegraflash-bsp"
mkdir -p "$bsp"

# A base DTB with __symbols__ so label-target overlays bind, matching the real
# L4T DTB (task 1.3 recorded SYMBOLS: present).
cat >"$work/base.dts" <<'EOF'
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

# initrd-flash.sh flashes kernel_$DTBFILE, sourcing DTBFILE from this file
# (tegraflash-bsp.bb writes it from KERNEL_DEVICETREE). It is the only thing in
# the BSP that names which SKU's tree this machine actually boots.
write_env() {
  printf 'BOOTDEV="mmcblk0p1"\nDTBFILE="%s"\nROOTFS_DEVICE="mmcblk0"\n' "$1" \
    >"$bsp/.env.initrd-flash"
}
write_env "tegra234-test-0005.dtb"

# Overlay fixtures, each adding an identifiable property to the same target.
make_dtbo() {
  local out="$1" prop="$2"
  cat >"$work/$prop.dts" <<EOF
/dts-v1/;
/plugin/;
&target_node {
    $prop = "present";
};
EOF
  dtc -@ -I dts -O dtb -o "$out" "$work/$prop.dts" 2>/dev/null
}

make_staging() {
  local dir="$1"
  shift
  mkdir -p "$dir"
  local entries=()
  for name in "$@"; do
    make_dtbo "$dir/$name.dtbo" "$name"
    entries+=("{\"name\": \"$name\", \"file\": \"$name.dtbo\", \"params\": {}, \"claimed_by\": null}")
  done
  local joined
  joined="$(
    IFS=,
    echo "${entries[*]}"
  )"
  printf '{"version": 1, "overlays": [%s]}\n' "$joined" >"$dir/overlays.manifest.json"
}

write_stone() {
  cat >"$1" <<EOF
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
    AVOCADO_STONE_INCLUDE_PATHS="${INC:-}" \
    AVOCADO_SDK_PREFIX='' \
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
printf 'not a device tree blob' >"$work/s3/broken.dtbo"
cat >"$work/s3/overlays.manifest.json" <<'EOF'
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
  # Deliberately WITHOUT the kernel_ prefix. tegra234-flash-helper.sh:636-637
  # does `rm -f kernel_$base` then recreates it from the un-prefixed $base, so a
  # merged DTB published as kernel_<name> is deleted before it is ever read,
  # and the board boots the stock tree with no overlay and no error. Verified
  # on hardware 2026-08-15 (scarthgap): kernel-dtb partitions p4/p7 contained a
  # valid DTB that did not carry the overlay marker.
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
cat >"$work/stone-nodisk.json" <<'EOF'
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
# stone resolves images.dtb by name, first input dir wins. A same-named DTB in
# the data dir would be picked over the merged copy in staging, shipping a tree
# with no overlays applied and reporting nothing.
make_staging "$work/s6" alpha
cp "$bsp/tegra234-test-0005.dtb" "$work/tegra234-test-0005.dtb"
if run_hook "$work/s6" "$work/stone.json" "$work/f6.json" >/dev/null 2>"$work/e6"; then
  bad "hook accepted a shadowing DTB in the data dir"
else
  if grep -qi "shadow" "$work/e6"; then
    ok "a DTB that would shadow the merged one is a hard error"
  else
    bad "shadowing case had no clear message: $(cat "$work/e6")"
  fi
fi
rm -f "$work/tegra234-test-0005.dtb"

# --- 7. drift guard: hook target must match the consumer's read -------------
# The provisioning run reads the manifest through the tegraflash engine, which
# declares every key it reads in avocado_tegraflash/manifest.py (KEYS). The
# launcher stone-provision-tegraflash.sh no longer names any of them.
engine="$here/../../../stone/tegra"
if [[ -f "$engine/avocado_tegraflash/manifest.py" ]]; then
  if python3 - "$engine" <<'PY' && jq -e '.storage_devices.rootdisk.images.dtb' "$work/f1.json" >/dev/null; then
import sys
sys.path.insert(0, sys.argv[1])
from avocado_tegraflash.manifest import KEYS
sys.exit(0 if any(k.section == "images" and k.name == "dtb" for k in KEYS) else 1)
PY
    ok "hook writes the same path the engine reads"
  else
    bad "hook target and the engine's manifest key have drifted apart"
  fi
else
  bad "engine manifest not found under $engine; drift guard cannot run"
fi

# --- 8. a malformed manifest entry fails clean, not with a traceback --------
# Every other bad input exits through die(); indexing a missing key would
# raise a bare KeyError instead. The distinction matters because the hook runs
# inside a build container, where a traceback is the least readable thing to
# land in the log.
make_staging "$work/s8" alpha
jq '.overlays[0] |= del(.file)' "$work/s8/overlays.manifest.json" >"$work/s8/m.json"
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
    >"$bsp/.env.initrd-flash"
  make_staging "$work/s9" alpha
  rm -f "$work/f9.json"
  if run_hook "$work/s9" "$work/stone.json" "$work/f9.json" >/dev/null 2>"$work/e9" \
    && [[ "$(jq -r '.storage_devices.rootdisk.images.dtb' "$work/f9.json")" == "tegra234-test-0005.dtb" ]]; then
    ok "DTBFILE parsed from: $form"
  else
    bad "DTBFILE form not handled: $form :: $(cat "$work/e9")"
  fi
done
write_env "tegra234-test-0005.dtb"

# --- 10-12. the BSP comes from the runtime input dir, not the SDK -----------
# Nothing stages tegraflash-bsp/ beside the SDK's stone manifest:
# avocado-img-bootfiles installs it into the runtime's dnf root,
# $AVOCADO_PREFIX/runtimes/$RUNTIME_NAME, which the CLI hands stone as an input
# dir and avocado-tegra-build-bootimg reads tegraflash-bsp/boot.img from. Here
# the manifest sits in a directory with no BSP, as the SDK's does, so a hook
# that resolves the BSP against the manifest's directory fails case 10.
prefix="$work/prefix"
rt_dir="$prefix/runtimes/rt"
mkdir -p "$rt_dir" "$work/sdk-stone"
cp -a "$bsp" "$rt_dir/tegraflash-bsp"
write_stone "$work/sdk-stone/stone-jetson-orin-nano.json"

# run_hook_rt STAGING FRAGMENT [env args]: no data-dir override, as in a real
# build. Options to env (-u NAME) must come before NAME=VALUE arguments.
run_hook_rt() {
  local staging="$1" fragment="$2"
  shift 2
  env -u AVOCADO_STONE_DATA_DIR "$@" \
    AVOCADO_DTBO_STAGING="$staging" \
    AVOCADO_OVERLAYS_MANIFEST="$staging/overlays.manifest.json" \
    AVOCADO_DELIVERY_FRAGMENT="$fragment" \
    AVOCADO_STONE_MANIFEST="$work/sdk-stone/stone-jetson-orin-nano.json" \
    "$hook"
}

make_staging "$work/s10" alpha
if run_hook_rt "$work/s10" "$work/f10.json" AVOCADO_PREFIX="$prefix" RUNTIME_NAME=rt \
  >/dev/null 2>"$work/e10"; then
  if [[ "$(jq -r '.storage_devices.rootdisk.images.dtb' "$work/f10.json")" == "tegra234-test-0005.dtb" ]] \
    && dtc -I dtb -O dts "$work/s10/tegra234-test-0005.dtb" 2>/dev/null | grep -q 'alpha = "present"'; then
    ok "the base DTB is read from \$AVOCADO_PREFIX/runtimes/\$RUNTIME_NAME and merged"
  else
    bad "runtime-dir resolution published the wrong tree: $(jq -c . "$work/f10.json")"
  fi
else
  bad "hook did not find the BSP in the runtime input dir: $(cat "$work/e10")"
fi

make_staging "$work/s11" alpha
if run_hook_rt "$work/s11" "$work/f11.json" -u RUNTIME_NAME AVOCADO_PREFIX="$prefix" \
  >/dev/null 2>"$work/e11"; then
  bad "hook resolved a BSP with no RUNTIME_NAME to locate it"
elif grep -q "Traceback" "$work/e11"; then
  bad "missing RUNTIME_NAME raised a traceback: $(cat "$work/e11")"
elif grep -q "RUNTIME_NAME" "$work/e11"; then
  ok "a missing RUNTIME_NAME is a hard error naming the variable"
else
  bad "missing RUNTIME_NAME had no clear message: $(cat "$work/e11")"
fi

# The runtime input dir is on stone's -i list, so a same-named DTB there would
# win the lookup if the CLI ever stopped prepending the staging dir.
make_staging "$work/s12" alpha
cp "$bsp/tegra234-test-0005.dtb" "$rt_dir/tegra234-test-0005.dtb"
if run_hook_rt "$work/s12" "$work/f12.json" AVOCADO_PREFIX="$prefix" RUNTIME_NAME=rt \
  >/dev/null 2>"$work/e12"; then
  bad "hook accepted a shadowing DTB in the runtime input dir"
elif grep -qi "shadow" "$work/e12"; then
  ok "a DTB shadowing the merged one in the runtime input dir is a hard error"
else
  bad "runtime-dir shadowing case had no clear message: $(cat "$work/e12")"
fi
rm -f "$rt_dir/tegra234-test-0005.dtb"

# --- 13. overlay params are refused, not dropped -----------------------------
# fdtoverlay takes only the .dtbo files, so a parameter would build with the
# compiled-in default while the overlay is still marked claimed. The CLI relies
# on each hook to refuse what it cannot apply.
make_staging "$work/s13" alpha
jq '.overlays[0].params = {"bus_speed": "400000"}' "$work/s13/overlays.manifest.json" >"$work/s13/m.json"
mv "$work/s13/m.json" "$work/s13/overlays.manifest.json"
if run_hook "$work/s13" "$work/stone.json" "$work/f13.json" >/dev/null 2>"$work/e13"; then
  bad "hook accepted an overlay with params it cannot apply"
elif grep -q "alpha" "$work/e13" && grep -qi "params" "$work/e13"; then
  ok "overlay params are a hard error naming the overlay"
else
  bad "params refusal did not name the overlay and params: $(cat "$work/e13")"
fi

# --- 14-16. a carrier BSP changes what gets flashed --------------------------
# At provision time the engine copies the carrier slot into the work dir after
# the stock BSP, applies carrier.env (CARRIER_ENV_DTBFILE re-points DTBFILE),
# then stages images.dtb over whatever the carrier shipped under that name. The
# merged stock tree is then either never flashed or replaces the carrier's own.
write_stone_carrier() {
  cat >"$1" <<'EOF2'
{
  "runtime": {"platform": "avocado-jetson-orin-nano"},
  "storage_devices": {
    "rootdisk": {
      "images": {
        "rootfs": "rootfs.erofs",
        "tegraflash_bsp": "tegraflash-bsp",
        "tegraflash_carrier_bsp": "carrier-bsp"
      }
    }
  }
}
EOF2
}
write_stone_carrier "$work/stone-carrier.json"
carrier="$work/carrier-bsp"

# 14. the carrier's env file re-points the DTB: the merged stock tree would not
# be flashed.
mkdir -p "$carrier"
printf 'CARRIER_LABEL="Test carrier"\nCARRIER_ENV_DTBFILE="tegra234-test-carrier.dtb"\n' >"$carrier/carrier.env"
make_staging "$work/s14" alpha
if run_hook "$work/s14" "$work/stone-carrier.json" "$work/f14.json" >/dev/null 2>"$work/e14"; then
  bad "hook merged into the stock DTB although the carrier re-points DTBFILE"
elif grep -q "carrier-bsp" "$work/e14" && grep -q "CARRIER_ENV_DTBFILE" "$work/e14"; then
  ok "a carrier that re-points DTBFILE is a hard error naming the carrier"
else
  bad "carrier DTBFILE refusal was unclear: $(cat "$work/e14")"
fi

# 15. the carrier ships a file under the base DTB's name (Shape A): the merged
# carrier copy is published under that name, covered in depth by case 19.
rm -f "$carrier/carrier.env"
cp "$bsp/tegra234-test-0005.dtb" "$carrier/tegra234-test-0005.dtb"
make_staging "$work/s15" alpha
if run_hook "$work/s15" "$work/stone-carrier.json" "$work/f15.json" >/dev/null 2>"$work/e15" \
  && dtc -I dtb -O dts "$work/s15/tegra234-test-0005.dtb" 2>/dev/null | grep -q 'alpha = "present"'; then
  ok "a carrier DTB under the base name is merged, not refused"
else
  bad "Shape A carrier was refused or not merged: $(cat "$work/e15")"
fi

# 16. an empty slot (only .placeholder) is the normal case and must not trip it.
rm -f "$carrier/tegra234-test-0005.dtb"
touch "$carrier/.placeholder"
make_staging "$work/s16" alpha
if run_hook "$work/s16" "$work/stone-carrier.json" "$work/f16.json" >/dev/null 2>"$work/e16"; then
  ok "an empty carrier slot does not trip the carrier check"
else
  bad "empty carrier slot was refused: $(cat "$work/e16")"
fi

# 16b. a populated carrier that leaves DTBFILE alone (label, flashvars) is fine.
printf 'CARRIER_LABEL="Test carrier"\n' >"$carrier/carrier.env"
make_staging "$work/s16b" alpha
if run_hook "$work/s16b" "$work/stone-carrier.json" "$work/f16b.json" >/dev/null 2>"$work/e16b"; then
  ok "a carrier that leaves DTBFILE alone is accepted"
else
  bad "carrier without a DTB override was refused: $(cat "$work/e16b")"
fi

# --- 17-18. a carrier from an extension's stone_include_paths -----------------
# Real carriers arrive through AVOCADO_STONE_INCLUDE_PATHS, which stone searches
# before the runtime dir; the runtime dir keeps only the .placeholder stub.
rm -f "$carrier/carrier.env"
ext="$work/ext-carrier"
mkdir -p "$work/inc-empty" "$ext/carrier-bsp"
printf 'CARRIER_LABEL="Ext carrier"\nCARRIER_ENV_DTBFILE="tegra234-test-carrier.dtb"\n' >"$ext/carrier-bsp/carrier.env"

# 17. the include-path carrier re-points DTBFILE: refused, naming where it is.
make_staging "$work/s17" alpha
if INC="$work/inc-empty::$ext" run_hook "$work/s17" "$work/stone-carrier.json" "$work/f17.json" >/dev/null 2>"$work/e17"; then
  bad "hook merged into the stock DTB although an include-path carrier re-points DTBFILE"
elif grep -q "$ext/carrier-bsp" "$work/e17" && grep -q "CARRIER_ENV_DTBFILE" "$work/e17"; then
  ok "an include-path carrier that re-points DTBFILE is a hard error naming it"
else
  bad "include-path carrier refusal was unclear: $(cat "$work/e17")"
fi

# 18. first match wins, as in stone: an earlier include path's empty slot is the
# one bundled, so the later carrier is not consulted.
mkdir -p "$work/inc-stub/carrier-bsp"
touch "$work/inc-stub/carrier-bsp/.placeholder"
make_staging "$work/s18" alpha
if INC="$work/inc-stub:$ext" run_hook "$work/s18" "$work/stone-carrier.json" "$work/f18.json" >/dev/null 2>"$work/e18"; then
  ok "the first include path holding the carrier slot is the one checked"
else
  bad "a carrier shadowed by an earlier include path was refused: $(cat "$work/e18")"
fi

# --- 19-30. a declared overlay is merged into the carrier-selected tree -------
# Provisioning lays the carrier slot over the stock BSP, applies carrier.env,
# then stages images.dtb under the published name. The tree that reaches the
# kernel-dtb partition is therefore the carrier's, so the hook merges into it
# and every fixture asserts the published tree's contents, not the exit code.

# make_tree OUT MARKER: the stock base tree plus a root property only this copy
# carries, so a merge into the wrong copy is visible in the result.
make_tree() {
  local out="$1" marker="$2"
  sed "s|^    #address-cells|    marker = \"$marker\";\n    #address-cells|" "$work/base.dts" >"$work/tree-$marker.dts"
  dtc -@ -I dts -O dtb -o "$out" "$work/tree-$marker.dts" 2>/dev/null
}

# new_slot NAME: an include-path root holding an empty carrier-bsp slot.
new_slot() {
  rm -rf "$work/inc-$1"
  mkdir -p "$work/inc-$1/carrier-bsp"
  slot="$work/inc-$1/carrier-bsp"
}

# prop FILE PATH PROPERTY: read one property from a compiled tree, empty if absent.
prop() {
  fdtget "$1" "$2" "$3" 2>/dev/null || true
}

# 19. Shape A: the slot ships the base name, no redirect.
new_slot a
make_tree "$slot/tegra234-test-0005.dtb" carrier-a
make_staging "$work/s19" alpha
if INC="$work/inc-a" run_hook "$work/s19" "$work/stone-carrier.json" "$work/f19.json" >"$work/o19" 2>"$work/e19"; then
  pub="$work/s19/tegra234-test-0005.dtb"
  if [[ "$(jq -r '.storage_devices.rootdisk.images.dtb' "$work/f19.json")" == "tegra234-test-0005.dtb" &&
  "$(prop "$pub" / marker)" == "carrier-a" &&
  "$(prop "$pub" /target-node alpha)" == "present" ]]; then
    ok "Shape A merges into the carrier's copy and publishes the base name"
  else
    bad "Shape A published tree lacks the carrier marker or the overlay"
  fi
  if grep -q "delivered 1 overlay(s) merged into tegra234-test-0005.dtb from carrier slot $slot for avocado-jetson-orin-nano: alpha" "$work/o19"; then
    ok "the success line names the tree and the carrier slot"
  else
    bad "success line for a carrier merge: $(cat "$work/o19")"
  fi
else
  bad "Shape A carrier was refused: $(cat "$work/e19")"
fi

# 20. Shape B into a tree the slot ships.
new_slot b
make_tree "$slot/tegra234-test-sel.dtb" carrier-b
printf 'CARRIER_ENV_DTBFILE="tegra234-test-sel.dtb"\n' >"$slot/carrier.env"
make_staging "$work/s20" alpha
if INC="$work/inc-b" run_hook "$work/s20" "$work/stone-carrier.json" "$work/f20.json" >/dev/null 2>"$work/e20"; then
  pub="$work/s20/tegra234-test-sel.dtb"
  if [[ "$(jq -r '.storage_devices.rootdisk.images.dtb' "$work/f20.json")" == "tegra234-test-sel.dtb" &&
  ! -e "$work/s20/tegra234-test-0005.dtb" &&
  "$(prop "$pub" / marker)" == "carrier-b" &&
  "$(prop "$pub" /target-node alpha)" == "present" ]]; then
    ok "Shape B merges into the slot-shipped redirect target and publishes its name"
  else
    bad "Shape B (slot tree) published the wrong name or tree"
  fi
else
  bad "Shape B into a slot tree was refused: $(cat "$work/e20")"
fi

# 21. Shape B into a stock BSP tree: the carrier only selects another SKU.
new_slot c
printf 'CARRIER_ENV_DTBFILE="tegra234-test-0003.dtb"\n' >"$slot/carrier.env"
make_staging "$work/s21" alpha
if INC="$work/inc-c" run_hook "$work/s21" "$work/stone-carrier.json" "$work/f21.json" >/dev/null 2>"$work/e21"; then
  pub="$work/s21/tegra234-test-0003.dtb"
  if [[ "$(jq -r '.storage_devices.rootdisk.images.dtb' "$work/f21.json")" == "tegra234-test-0003.dtb" &&
  "$(prop "$pub" /target-node alpha)" == "present" &&
  "$(prop "$bsp/tegra234-test-0003.dtb" /target-node alpha)" == "" ]]; then
    ok "Shape B merges into the stock BSP's copy when the slot does not ship it"
  else
    bad "Shape B (stock tree) published the wrong name or tree"
  fi
else
  bad "Shape B into a stock tree was refused: $(cat "$work/e21")"
fi

# 22. the slot's copy wins over the stock one, as when provisioning lays the
# carrier over the BSP.
new_slot d
make_tree "$slot/tegra234-test-0003.dtb" carrier-d
printf 'CARRIER_ENV_DTBFILE="tegra234-test-0003.dtb"\n' >"$slot/carrier.env"
make_staging "$work/s22" alpha
if INC="$work/inc-d" run_hook "$work/s22" "$work/stone-carrier.json" "$work/f22.json" >/dev/null 2>"$work/e22" \
  && [[ "$(prop "$work/s22/tegra234-test-0003.dtb" / marker)" == "carrier-d" ]]; then
  ok "a redirect target in both places resolves to the carrier slot's copy"
else
  bad "slot copy did not take precedence over the stock BSP: $(cat "$work/e22")"
fi

# 23. two assignments: the last one wins, as in the engine.
new_slot e
printf 'CARRIER_ENV_DTBFILE="tegra234-test-0000.dtb"\nCARRIER_ENV_DTBFILE="tegra234-test-0003.dtb"\n' >"$slot/carrier.env"
make_staging "$work/s23" alpha
if INC="$work/inc-e" run_hook "$work/s23" "$work/stone-carrier.json" "$work/f23.json" >/dev/null 2>"$work/e23" \
  && [[ "$(jq -r '.storage_devices.rootdisk.images.dtb' "$work/f23.json")" == "tegra234-test-0003.dtb" &&
  "$(prop "$work/s23/tegra234-test-0003.dtb" /target-node alpha)" == "present" ]]; then
  ok "with two CARRIER_ENV_DTBFILE lines the last one wins"
else
  bad "first-wins or wrong tree for duplicate assignments: $(cat "$work/e23" 2>/dev/null)"
fi

# 23b. only column-0 assignments count: an indented line is ignored.
new_slot e2
printf '  CARRIER_ENV_DTBFILE="tegra234-test-9999.dtb"\n' >"$slot/carrier.env"
make_staging "$work/s23b" alpha
if INC="$work/inc-e2" run_hook "$work/s23b" "$work/stone-carrier.json" "$work/f23b.json" >/dev/null 2>"$work/e23b" \
  && [[ "$(jq -r '.storage_devices.rootdisk.images.dtb' "$work/f23b.json")" == "tegra234-test-0005.dtb" ]]; then
  ok "an indented CARRIER_ENV_DTBFILE line is not a redirect"
else
  bad "indented assignment was treated as a redirect: $(cat "$work/e23b")"
fi

# 24. single quotes, and a double-quoted value wrapping single quotes, are
# stripped in the engine's order.
for form in "'tegra234-test-0003.dtb'" "\"'tegra234-test-0003.dtb'\"" "tegra234-test-0003.dtb"; do
  new_slot f
  printf 'CARRIER_ENV_DTBFILE=%s\n' "$form" >"$slot/carrier.env"
  make_staging "$work/s24" alpha
  rm -f "$work/f24.json"
  if INC="$work/inc-f" run_hook "$work/s24" "$work/stone-carrier.json" "$work/f24.json" >/dev/null 2>"$work/e24" \
    && [[ "$(jq -r '.storage_devices.rootdisk.images.dtb' "$work/f24.json")" == "tegra234-test-0003.dtb" ]]; then
    ok "redirect value parsed from: $form"
  else
    bad "redirect value form not handled: $form :: $(cat "$work/e24")"
  fi
done

# 25. a redirect to a tree that exists nowhere is refused, naming the value and
# both directories searched.
new_slot g
printf 'CARRIER_ENV_DTBFILE="tegra234-test-nowhere.dtb"\n' >"$slot/carrier.env"
make_staging "$work/s25" alpha
if INC="$work/inc-g" run_hook "$work/s25" "$work/stone-carrier.json" "$work/f25.json" >/dev/null 2>"$work/e25"; then
  bad "hook accepted a redirect whose target exists nowhere"
elif grep -q "tegra234-test-nowhere.dtb" "$work/e25" && grep -q "$slot" "$work/e25" && grep -q "$bsp" "$work/e25" \
  && [[ ! -e "$work/s25/tegra234-test-nowhere.dtb" && ! -e "$work/f25.json" ]]; then
  ok "a redirect to a missing tree is refused naming the value and both directories"
else
  bad "missing-target refusal was unclear or left a tree: $(cat "$work/e25")"
fi

# 26. a Shape A file together with a redirect to another name is refused,
# naming both signals.
new_slot h
make_tree "$slot/tegra234-test-0005.dtb" carrier-h
printf 'CARRIER_ENV_DTBFILE="tegra234-test-0003.dtb"\n' >"$slot/carrier.env"
make_staging "$work/s26" alpha
if INC="$work/inc-h" run_hook "$work/s26" "$work/stone-carrier.json" "$work/f26.json" >/dev/null 2>"$work/e26"; then
  bad "hook accepted a Shape A file together with a disagreeing redirect"
elif grep -q "tegra234-test-0005.dtb" "$work/e26" && grep -q "tegra234-test-0003.dtb" "$work/e26" && grep -q "$slot" "$work/e26" \
  && [[ ! -e "$work/s26/tegra234-test-0005.dtb" && ! -e "$work/f26.json" ]]; then
  ok "a Shape A file plus a disagreeing redirect is refused naming both"
else
  bad "disagreeing-signals refusal was unclear or left a tree: $(cat "$work/e26")"
fi

# 26b. a redirect equal to the base name is Shape A, not a disagreement.
new_slot h2
make_tree "$slot/tegra234-test-0005.dtb" carrier-h2
printf 'CARRIER_ENV_DTBFILE="tegra234-test-0005.dtb"\n' >"$slot/carrier.env"
make_staging "$work/s26b" alpha
if INC="$work/inc-h2" run_hook "$work/s26b" "$work/stone-carrier.json" "$work/f26b.json" >/dev/null 2>"$work/e26b" \
  && [[ "$(prop "$work/s26b/tegra234-test-0005.dtb" / marker)" == "carrier-h2" ]]; then
  ok "a redirect equal to the base name merges into the carrier's copy"
else
  bad "redirect equal to the base name was refused or mis-merged: $(cat "$work/e26b")"
fi

# 27. an unsafe redirect value is refused before any lookup.
for unsafe in '../x.dtb' 'sub/x.dtb' '.' '..' '""'; do
  new_slot i
  printf 'CARRIER_ENV_DTBFILE=%s\n' "$unsafe" >"$slot/carrier.env"
  make_staging "$work/s27" alpha
  rm -f "$work/f27.json"
  if INC="$work/inc-i" run_hook "$work/s27" "$work/stone-carrier.json" "$work/f27.json" >/dev/null 2>"$work/e27"; then
    bad "hook accepted an unsafe redirect: $unsafe"
  elif grep -q "CARRIER_ENV_DTBFILE" "$work/e27" && grep -q "$slot" "$work/e27" && [[ ! -e "$work/f27.json" ]]; then
    ok "an unsafe redirect is refused: $unsafe"
  else
    bad "unsafe redirect refusal was unclear: $unsafe :: $(cat "$work/e27")"
  fi
done

# 28. a slot holding only unrelated files merges into the stock base tree.
new_slot j
printf 'x' >"$slot/notes.txt"
make_staging "$work/s28" alpha
if INC="$work/inc-j" run_hook "$work/s28" "$work/stone-carrier.json" "$work/f28.json" >"$work/o28" 2>"$work/e28" \
  && [[ "$(jq -r '.storage_devices.rootdisk.images.dtb' "$work/f28.json")" == "tegra234-test-0005.dtb" &&
  "$(prop "$work/s28/tegra234-test-0005.dtb" /target-node alpha)" == "present" ]]; then
  ok "a slot with no tree change merges into the stock base tree"
else
  bad "unrelated-files slot was refused or mis-merged: $(cat "$work/e28")"
fi

# 29. overlays apply in declared order on a carrier tree: the second targets a
# node the first creates.
new_slot k
make_tree "$slot/tegra234-test-0005.dtb" carrier-k
mkdir -p "$work/s29"
cat >"$work/mk.dts" <<'EOT'
/dts-v1/;
/plugin/;
&target_node {
    made_by_first {
        v = "1";
    };
};
EOT
cat >"$work/use.dts" <<'EOT'
/dts-v1/;
/plugin/;
&target_node {
    made_by_first {
        w = "2";
    };
};
EOT
dtc -@ -I dts -O dtb -o "$work/s29/first.dtbo" "$work/mk.dts" 2>/dev/null
dtc -@ -I dts -O dtb -o "$work/s29/second.dtbo" "$work/use.dts" 2>/dev/null
printf '{"version": 1, "overlays": [{"name": "first", "file": "first.dtbo", "params": {}, "claimed_by": null}, {"name": "second", "file": "second.dtbo", "params": {}, "claimed_by": null}]}\n' >"$work/s29/overlays.manifest.json"
if INC="$work/inc-k" run_hook "$work/s29" "$work/stone-carrier.json" "$work/f29.json" >/dev/null 2>"$work/e29"; then
  pub="$work/s29/tegra234-test-0005.dtb"
  if [[ "$(prop "$pub" / marker)" == "carrier-k" &&
  "$(prop "$pub" /target-node/made_by_first v)" == "1" &&
  "$(prop "$pub" /target-node/made_by_first w)" == "2" ]]; then
    ok "two overlays merge in declared order into a carrier tree"
  else
    bad "second overlay did not land on the first's node in the carrier tree"
  fi
else
  bad "two-overlay carrier merge failed: $(cat "$work/e29")"
fi

# 30. an fdtoverlay failure on a carrier tree leaves no staged tree behind.
new_slot l
make_tree "$slot/tegra234-test-0005.dtb" carrier-l
mkdir -p "$work/s30"
printf 'not a device tree blob' >"$work/s30/broken.dtbo"
cat >"$work/s30/overlays.manifest.json" <<'EOT'
{"version": 1, "overlays": [{"name": "broken", "file": "broken.dtbo", "params": {}, "claimed_by": null}]}
EOT
if INC="$work/inc-l" run_hook "$work/s30" "$work/stone-carrier.json" "$work/f30.json" >/dev/null 2>"$work/e30"; then
  bad "hook accepted an unmergeable overlay on a carrier tree"
elif [[ ! -e "$work/s30/tegra234-test-0005.dtb" && ! -e "$work/f30.json" ]]; then
  ok "an fdtoverlay failure leaves no staged tree and no fragment"
else
  bad "failed merge left a staged tree or fragment behind"
fi

echo
echo "passed: $pass  failed: $fail"
[[ "$fail" -eq 0 ]]
