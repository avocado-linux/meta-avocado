#!/usr/bin/env bash
# Host test for retarget_module_sku_t264() in initrd-flash.sh: the P3834 module
# SKU read off the board at flash time must move every module-specific flash
# file to that SKU, leave the SOM-SKU-independent ones alone, and refuse a
# module it has no files for rather than mis-flashing SDRAM training.
#
# The function is extracted rather than sourced: initrd-flash.sh is a script,
# not a library, and sourcing it would run the flash.
set -u
here=$(cd "$(dirname "$0")" && pwd)
script=$here/../tegra-helper-scripts/initrd-flash.sh
w=$(mktemp -d); trap 'rm -rf "$w"' EXIT
pass=0; fail=0; ok(){ echo "  ok   - $1"; pass=$((pass+1)); }; bad(){ echo "  FAIL - $1"; fail=$((fail+1)); }

eval "$(awk '/^retarget_module_sku_t264\(\) \{/,/^\}/' "$script")"
if ! declare -f retarget_module_sku_t264 >/dev/null; then
    echo "FAIL - could not extract retarget_module_sku_t264 from $script"; exit 1
fi

# Real flashvars lines from avocado-jetson-agx-thor's tegraflash-bsp: the seven
# module-specific entries, plus the p3834-xxxx / CHECK_ entries that must not
# move. The -adv BPMP DTB is the shape a carrier extension leaves behind.
write_flashvars() {
    local sku="$1"
    cat > "$w/flashvars" <<VARS
PLUGIN_MANAGER_OVERLAYS="tegra264-p4071-0000+p3834-xxxx-dynamic.dtbo"
BCTFILE="tegra264-p3834-$sku-sdram-bct-l4t.dts"
BPFDTB_FILE="tegra264-bpmp-3834-$sku-4071-xxxx-adv.dtb"
BPF_FILE="bpmp_t264-TA1090SA-A1_prod.bin"
BPMP_MEM_CONFIG="tegra264-p3834-$sku-sdram-dfs.dts"
CHIP_SKU="00:00:00:A0"
DTB_FILE="tegra264-p4071-0000+p3834-$sku-nv.dtb"
MISC_CONFIG="tegra264-mb1-bct-misc-p3834-$sku-p4071-0000.dts"
PINMUX_CONFIG="tegra264-mb1-bct-pinmux-p3834-xxxx-p4071-0000.dts"
PMIC_CONFIG="tegra264-mb1-bct-pmic-p3834-$sku-p4071-0000.dts"
RAMCODE="12"
WB0SDRAM_BCT="tegra264-p3834-$sku-sdram-bct-warmboot-l4t.dts"
CHECK_BOARDID="3834"
CHECK_BOARDSKU="0008"
VARS
}

# $1 board id, $2 board sku, $3 flashvars sku to start from
run() {
    write_flashvars "$3"
    DTBFILE="tegra264-p4071-0000+p3834-$3-nv.dtb"
    EMC_BCT="tegra264-p3834-$3-sdram-bct-l4t.dts"
    BOARDID="$1" BOARDSKU="$2"
    retarget_module_sku_t264 2>&1
}
cd "$w" || exit 1

msg=$(run 3834 0000 0008); rc=$?
{ [ $rc -eq 0 ] && [ "$(grep -c 'p3834-0000\|3834-0000-4071' "$w/flashvars")" = 7 ] \
    && ! grep -q '3834-0008' "$w/flashvars"; } \
    && ok "a T4000 moves all seven module files to p3834-0000" \
    || bad "T4000: rc=$rc $msg"$'\n'"$(cat "$w/flashvars")"

grep -q 'p3834-xxxx-dynamic' "$w/flashvars" && grep -q 'pinmux-p3834-xxxx' "$w/flashvars" \
    && ok "the SOM-SKU-independent p3834-xxxx files are left alone" \
    || bad "p3834-xxxx rewritten: $(cat "$w/flashvars")"

grep -q '^CHECK_BOARDSKU="0008"' "$w/flashvars" && grep -q '^CHECK_BOARDID="3834"' "$w/flashvars" \
    && ok "CHECK_BOARDSKU and CHECK_BOARDID are not touched" \
    || bad "CHECK_ rewritten: $(cat "$w/flashvars")"

grep -q '^BPF_FILE="bpmp_t264-TA1090SA-A1_prod.bin"' "$w/flashvars" \
    && grep -q '^CHIP_SKU="00:00:00:A0"' "$w/flashvars" && grep -q '^RAMCODE="12"' "$w/flashvars" \
    && ok "BPF_FILE, CHIP_SKU and RAMCODE are left to the flash helper" \
    || bad "chip-derived vars rewritten: $(cat "$w/flashvars")"

# The .env.initrd-flash copies are already shell variables by this point, so
# they are patched in place rather than in the file.
run 3834 0000 0008 >/dev/null; msg="$DTBFILE $EMC_BCT"
[ "$msg" = "tegra264-p4071-0000+p3834-0000-nv.dtb tegra264-p3834-0000-sdram-bct-l4t.dts" ] \
    && ok "DTBFILE and EMC_BCT follow the module" || bad "env vars: $msg"

# A carrier that baked the T4000 must move the other way just as cleanly.
msg=$(run 3834 0008 0000); rc=$?
{ [ $rc -eq 0 ] && ! grep -q '3834-0000' "$w/flashvars" \
    && grep -q 'bpmp-3834-0008-4071-xxxx-adv.dtb' "$w/flashvars"; } \
    && ok "a T5000 on T4000-baked flashvars retargets in reverse" \
    || bad "reverse: rc=$rc $msg"$'\n'"$(cat "$w/flashvars")"

msg=$(run 3834 0008 0008); rc=$?
{ [ $rc -eq 0 ] && grep -q 'p3834-0008-sdram-bct-l4t' "$w/flashvars" \
    && ! grep -q '3834-0000' "$w/flashvars"; } \
    && ok "the matching SKU is a no-op" || bad "no-op: rc=$rc $msg"

# Mis-flashing a P3834-0005 with T5000 SDRAM training is not a soft failure, so
# an SKU we ship no files for has to stop the flash, not guess.
msg=$(run 3834 0005 0008); rc=$?
{ [ $rc -ne 0 ] && echo "$msg" | grep -q 'unsupported P3834 module SKU' \
    && grep -q 'p3834-0008-sdram-bct-l4t' "$w/flashvars"; } \
    && ok "an unknown module SKU aborts with flashvars untouched" || bad "unknown SKU: $msg"

msg=$(run 3701 0008 0008); rc=$?
{ [ $rc -eq 0 ] && grep -q 'p3834-0008-sdram-bct-l4t' "$w/flashvars"; } \
    && ok "a non-P3834 board is left alone" || bad "other board: rc=$rc $msg"

echo; echo "passed: $pass  failed: $fail"; [ $fail -eq 0 ]
