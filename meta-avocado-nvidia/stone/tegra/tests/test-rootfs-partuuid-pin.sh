#!/usr/bin/env bash
#
# The rootfs PARTUUIDs provisioning names on the kernel command line must be
# the ones that end up in the GPT.
#
# stone-provision-tegraflash.sh generates a PARTUUID per slot, bakes them into
# the repacked boot.img command line, and substitutes them for the APPUUID /
# APPUUID_b placeholders in the layout it flashes. make-sdcard.sh then writes
# the GPT from that layout via nvflashxmlparse and sgdisk. make-sdcard.sh used
# to parse unique_guid and never pass it to sgdisk, so provisioning succeeded
# while the initrd searched for a PARTUUID that was never written.
#
# This runs the real substitution block, the real nvflashxmlparse and the real
# make_partitions against a sparse image, then reads the GPT back.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NV="$SCRIPT_DIR/../../.."
PROVISION="$SCRIPT_DIR/../stone-provision-tegraflash.sh"
HELPERS="$NV/recipes-bsp/tegra-binaries/tegra-helper-scripts"
LAYOUTS="$NV/recipes-bsp/tegra-binaries/tegra-storage-layout"
failures=0

pass() { printf '  ok   %s\n' "$1"; }
fail() {
  printf '  FAIL %s\n' "$1"
  failures=$((failures + 1))
}

for f in "$PROVISION" "$HELPERS/make-sdcard.sh" "$HELPERS/nvflashxmlparse.py" \
  "$LAYOUTS/external-flash.xml" "$LAYOUTS/internal-flash-emmc.xml"; do
  [ -f "$f" ] || {
    echo "not found: $f" >&2
    exit 1
  }
done

# A skip is only honest off CI; in CI a missing tool must not pass as coverage.
for tool in sgdisk python3; do
  if ! command -v "$tool" >/dev/null; then
    echo "test-rootfs-partuuid-pin: $tool not installed"
    [ -n "${CI:-}" ] && exit 1
    exit 77
  fi
done

echo "test-rootfs-partuuid-pin: $PROVISION"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

A=11111111-2222-4333-8444-555555555555
B=AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE

# The substitution block runs at top level in the provision script, so lift it
# out rather than running a flash.
awk '/^if \[ -n "\$app_partuuid" \]; then$/{f=1} f{print} f&&/^fi$/{exit}' \
  "$PROVISION" > "$work/subst.sh"
if ! grep -q 'APPUUID' "$work/subst.sh"; then
  fail "could not extract the PARTUUID substitution block"
  echo "test-rootfs-partuuid-pin: FAIL (1)"
  exit 1
fi

# The same fill tegraflash-bsp.bb's process_flash_xml applies, with small sizes,
# leaving APPUUID/APPUUID_b for provisioning.
fill_layout() {
  sed -e "s,LNXFILE_b,boot.img," -e "s,LNXFILE,boot.img," -e "s,LNXSIZE,67108864," \
    -e "s,APPSIZE,67108864,g" -e "s,EXT_NUM_SECTORS,4194304," -e "s,INT_NUM_SECTORS,4194304," \
    -e "s,RECNAME,recovery," -e "s,RECSIZE,1048576,g" -e "s,RECDTB-NAME,recovery-dtb," \
    -e "s,ESP_FILE,esp.img," -e "/RECFILE/d" -e "/RECDTB-FILE/d" "$1" > "$2"
}

# run_subst <layout> -> rc; runs the block the way the script does.
run_subst() {
  (
    build_dir="$work/build"
    mkdir -p "$build_dir"
    cp "$1" "$build_dir/external-flash.xml.in"
    # Read by the sourced block below.
    # shellcheck disable=SC2034
    app_partuuid="$A"
    # shellcheck disable=SC2034
    app_b_partuuid="$B"
    # shellcheck disable=SC1091
    . "$work/subst.sh"
  ) >"$work/subst.out" 2>&1
}

# guid_of <layout> <partition name>
guid_of() {
  python3 - "$1" "$2" <<'EOF'
import sys, xml.etree.ElementTree as ET
for p in ET.parse(sys.argv[1]).iter('partition'):
    if p.get('name') == sys.argv[2]:
        g = p.find('unique_guid')
        print('' if g is None else g.text.strip())
EOF
}

for layout in external-flash.xml internal-flash-emmc.xml; do
  fill_layout "$LAYOUTS/$layout" "$work/$layout"
  if run_subst "$work/$layout"; then
    out="$work/build/external-flash.xml.in"
    if [ "$(guid_of "$out" APP)" = "$A" ] && [ "$(guid_of "$out" APP_b)" = "$B" ] \
      && ! grep -q APPUUID "$out"; then
      pass "$layout: APP gets slot A, APP_b gets slot B, no placeholder left"
    else
      fail "$layout: APP=$(guid_of "$out" APP) APP_b=$(guid_of "$out" APP_b)"
    fi
  else
    fail "$layout: substitution failed: $(head -3 "$work/subst.out")"
  fi
done

# A layout that is not the templated one must stop the flash, not write GUIDs
# that disagree with the command line. APPUUID_b contains APPUUID, so each
# placeholder has to be checked on its own.
sed 's,<unique_guid> APPUUID </unique_guid>,<unique_guid> </unique_guid>,' \
  "$work/external-flash.xml" > "$work/no-a.xml"
if grep -q 'APPUUID_b' "$work/no-a.xml" && ! grep -q 'APPUUID ' "$work/no-a.xml"; then
  if run_subst "$work/no-a.xml"; then
    fail "a layout missing only the slot-A placeholder was accepted"
  else
    pass "a layout missing only the slot-A placeholder is rejected"
  fi
else
  fail "could not build the slot-A-less layout"
fi

sed 's,APPUUID_b,,' "$work/external-flash.xml" > "$work/no-b.xml"
if run_subst "$work/no-b.xml"; then
  fail "a layout missing the slot-B placeholder was accepted"
else
  pass "a layout missing the slot-B placeholder is rejected"
fi

# Through to the disk: nvflashxmlparse -> make_partitions -> sgdisk -> GPT.
run_subst "$work/external-flash.xml" || fail "substitution for the GPT check failed"
awk '/^(find_finalpart|make_partitions)\(\) \{/{f=1} f{print} f&&/^\}$/{f=0}' \
  "$HELPERS/make-sdcard.sh" > "$work/mkparts.sh"
truncate -s 2G "$work/disk.img"
if bash -c '
  . "$1"
  output="$2"
  mapfile PARTS < <(python3 "$3" -t rootfs "$4")
  find_finalpart && make_partitions
' _ "$work/mkparts.sh" "$work/disk.img" "$HELPERS/nvflashxmlparse.py" \
  "$work/build/external-flash.xml.in" >"$work/mk.out" 2>&1; then
  gpt_guid() {
    sgdisk -p "$work/disk.img" | awk -v n="$1" '$NF==n{print $1}' | while read -r num; do
      sgdisk -i "$num" "$work/disk.img" | awk '/unique GUID/{print $4}'
    done
  }
  got_a=$(gpt_guid APP)
  got_b=$(gpt_guid APP_b)
  if [ "$got_a" = "$A" ] && [ "$got_b" = "$B" ]; then
    pass "the GPT carries the pinned PARTUUIDs for APP and APP_b"
  else
    fail "GPT PARTUUIDs: APP=$got_a APP_b=$got_b, expected $A / $B"
  fi
else
  fail "make_partitions failed: $(tail -3 "$work/mk.out")"
fi

# The command line and the layout must name the same values. The pattern is the
# literal source line, so the variables must not expand.
# shellcheck disable=SC2016
if grep -q 'boot_cmdline="avocado.root_partuuid=$app_partuuid avocado.root_partuuid_b=$app_b_partuuid"' "$PROVISION"; then
  pass "the boot.img command line names the same variables the layout is filled from"
else
  fail "boot_cmdline no longer carries \$app_partuuid/\$app_b_partuuid"
fi

echo
if [ "$failures" -eq 0 ]; then
  echo "test-rootfs-partuuid-pin: PASS"
  exit 0
fi
echo "test-rootfs-partuuid-pin: FAIL ($failures)"
exit 1
