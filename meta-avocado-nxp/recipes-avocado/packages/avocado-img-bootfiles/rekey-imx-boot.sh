#!/bin/sh
# rekey-imx-boot.sh - rebuild a prebuilt i.MX8M imx-boot so U-Boot enforces the
# project's FIT signing key. No U-Boot source build: the feed ships imx-boot's
# own inputs (DDR firmware, SPL, u-boot-nodtb, the unkeyed control DTB, bl31,
# tee.bin, soc.mak, mkimage_fit_atf.sh) in imx-boot-tools/, and this script
# injects the public key into the control DTB and runs the same soc.mak targets
# the distro build ran, with the SDK's mkimage_imx8 in place of the one soc.mak
# would compile.
#
#   rekey-imx-boot.sh <imx-boot-tools dir> <key dir with FIT.key/FIT.crt> <out dir> [<algo>]
#
# <algo> is mkimage's "<hash>,<rsaNNNN>" string (default sha256,rsa2048) and
# must match the FIT's signature nodes.
#
# Outputs, named exactly as the feed names them so stone's imx_boot* image keys
# resolve to these first: imx-boot-<machine>-<cfg>.bin-<target> per target and
# imx-boot -> the first target. Machine facts come from rekey.env next to this
# script (written by avocado-img-bootfiles from the machine configuration).
set -eu

TOOLS=$1; KEYDIR=$2; OUT=$3; ALGO=${4:-sha256,rsa2048}
[ -f "$TOOLS/rekey.env" ] || { echo "rekey-imx-boot: no $TOOLS/rekey.env - this feed does not support re-keying imx-boot" >&2; exit 1; }
[ -f "$KEYDIR/FIT.key" ] && [ -f "$KEYDIR/FIT.crt" ] || { echo "rekey-imx-boot: $KEYDIR must hold FIT.key and FIT.crt" >&2; exit 1; }
# shellcheck disable=SC1091
. "$TOOLS/rekey.env"
: "${MACHINE:?}" "${SOC:?}" "${UBOOT_CONFIG_EXTRA:?}" "${UBOOT_DTB_NAME:?}" "${IMXBOOT_TARGETS:?}" "${DDR_FIRMWARE_NAME:?}"

for t in fdt_add_pubkey mkimage mkimage_imx8 lz4 make; do
    command -v "$t" >/dev/null || { echo "rekey-imx-boot: missing tool: $t" >&2; exit 1; }
done

W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
S="$W/iMX8M"; mkdir -p "$S" "$W/scripts"

# soc.mak shells out to two helpers imx-mkimage keeps in ../scripts and the
# feed does not ship. pad_image.sh: 16-byte-align the concatenation of its
# arguments by growing the last one (truncate, not objcopy: same bytes, and the
# SDK has no host objcopy). dtb_check.sh: place the control DTB as evk.dtb.
cat > "$W/scripts/pad_image.sh" <<'PAD'
#!/bin/sh
total=0; last=
for f in "$@"; do [ -f "$f" ] || exit 0; total=$((total + $(wc -c < "$f"))); last=$f; done
padded=$(( (total + 15) & ~15 ))
[ "$total" = "$padded" ] || truncate -s $(( $(wc -c < "$last") + padded - total )) "$last"
PAD
cat > "$W/scripts/dtb_check.sh" <<'DTB'
#!/bin/sh
# $1 = <plat>-evk.dtb (unused here), $2 = output name, $3.. = dtbs
out=$2; shift 2
src=${1:-}; [ -n "$src" ] && [ -f "$src" ] || src=$(ls ./*.dtb-* 2>/dev/null | head -1)
cp "$src" "$out"
DTB
# u-boot-spl-ddr.bin pads each DDR firmware blob with objcopy, which the SDK
# does not carry either. Cover the one invocation shape soc.mak uses:
#   objcopy -I binary -O binary --pad-to <size> --gap-fill=0x0 <in> <out>
cat > "$W/scripts/objcopy" <<'OBJ'
#!/bin/sh
pad=; in=; out=
while [ $# -gt 0 ]; do
    case "$1" in
        -I|-O) shift ;;
        --pad-to) pad=$2; shift ;;
        --pad-to=*) pad=${1#*=} ;;
        --gap-fill=*|--gap-fill) [ "$1" = --gap-fill ] && shift ;;
        -*) echo "objcopy shim: unsupported option $1" >&2; exit 1 ;;
        *) if [ -z "$in" ]; then in=$1; else out=$1; fi ;;
    esac
    shift
done
[ -n "$in" ] && [ -n "$out" ] || { echo "objcopy shim: need <in> <out>" >&2; exit 1; }
cp "$in" "$out"
[ -z "$pad" ] || truncate -s "$((pad))" "$out"
OBJ
chmod +x "$W/scripts/"*
PATH="$W/scripts:$PATH"; export PATH

# Inputs under the names soc.mak expects (mirrors imx-boot's compile_mx8m).
for fw in $DDR_FIRMWARE_NAME; do cp "$TOOLS/$fw" "$S/"; done
cp "$TOOLS/u-boot-spl.bin-${MACHINE}-${UBOOT_CONFIG_EXTRA}"   "$S/u-boot-spl.bin"
cp "$TOOLS/u-boot-nodtb.bin-${MACHINE}-${UBOOT_CONFIG_EXTRA}" "$S/u-boot-nodtb.bin"
cp "$TOOLS/u-boot-${MACHINE}.bin-${UBOOT_CONFIG_EXTRA}"       "$S/u-boot.bin"
bl31=$(ls "$TOOLS"/bl31-*.bin* | head -1); cp "$bl31" "$S/bl31.bin"
[ -f "$TOOLS/tee.bin" ] && cp "$TOOLS/tee.bin" "$S/tee.bin"
for f in signed_hdmi_imx8m.bin signed_dp_imx8m.bin; do [ -f "$TOOLS/$f" ] && cp "$TOOLS/$f" "$S/"; done
cp "$TOOLS/soc.mak" "$TOOLS/mkimage_fit_atf.sh" "$S/"
DTB="${UBOOT_DTB_NAME}-${UBOOT_CONFIG_EXTRA}"
[ -f "$TOOLS/$DTB" ] || DTB="$UBOOT_DTB_NAME"
cp "$TOOLS/$DTB" "$S/$DTB"

# soc.mak compiles ./mkimage_imx8 from ../iMX8M/mkimage_imx8.c. Give it the
# SDK's binary under that name and a source file that is older, so the rule is
# already up to date and nothing is compiled.
ln -s "$(command -v mkimage_imx8)" "$S/mkimage_imx8"
touch -d 2000-01-01 "$S/mkimage_imx8.c"

# The whole point: the project's public key into the control DTB, as
# /signature/key-FIT with required = "conf". Creates or replaces the node, so
# an unkeyed distro DTB and a distro-keyed one both end up enforcing this key.
fdt_add_pubkey -a "$ALGO" -k "$KEYDIR" -n FIT -r conf "$S/$DTB"

mkdir -p "$OUT"
first=
for target in $IMXBOOT_TARGETS; do
    out="imx-boot-${MACHINE}-${UBOOT_CONFIG_EXTRA}.bin-${target}"
    ( cd "$S" && make -s -f soc.mak SOC="$SOC" SOC_DIR=iMX8M CC=false dtbs="$DTB" ${MKIMAGE_ARGS:-} OUTIMG="$out" "$target" >/dev/null )
    install -m 0644 "$S/$out" "$OUT/$out"
    [ -n "$first" ] || first=$out
    # soc.mak's rules only rebuild u-boot.itb once; each target re-packs it.
done
ln -sf "$first" "$OUT/imx-boot"
install -m 0644 "$S/$DTB" "$OUT/u-boot-${MACHINE}.dtb.keyed"
echo "rekey-imx-boot: imx-boot for $MACHINE now enforces $(openssl x509 -in "$KEYDIR/FIT.crt" -noout -subject 2>/dev/null || echo "the key in $KEYDIR") -> $OUT/imx-boot ($first)"
