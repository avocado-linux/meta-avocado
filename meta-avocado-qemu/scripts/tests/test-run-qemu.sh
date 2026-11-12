#!/usr/bin/env bash
# Host test for run-qemu: machine naming, the TPM restriction, the image lookup
# under build/tmp/deploy/stone/_build, the explicit --image path, the resize
# rule, QEMU selection, the boot-firmware lookup and the exact QEMU command
# lines. Every case runs in its own temp work directory with stub QEMU tools, so
# no real QEMU starts. Run it by hand after any change to the runner.
# shellcheck disable=SC2015 # `check && ok || bad`: ok only echoes and counts, so bad runs only when the check failed
set -u
here=$(cd "$(dirname "$0")" && pwd)
script=${1:-$here/../run-qemu}
w=$(mktemp -d)
trap 'rm -rf "$w"' EXIT
pass=0
fail=0
ok() {
  echo "  ok   - $1"
  pass=$((pass + 1))
}
bad() {
  echo "  FAIL - $1"
  fail=$((fail + 1))
}

# Stub QEMU tools. STUB_LOG collects what they were asked to do; the qemu-img
# stub honours `resize -f raw <image> <N>M` by truncating the sparse image.
log=$w/stub.log
export STUB_LOG=$log
: >"$log"
hs=$w/hoststubs
tools=$w/tools
mkdir -p "$hs" "$tools"
mkstubs() {
  local d=$1
  # shellcheck disable=SC2016 # $* belongs to the generated stub
  printf '#!/bin/sh\necho "qemu-launch $*" >>"$STUB_LOG"\nexit "${STUB_QEMU_RC:-0}"\n' >"$d/qemu-system-x86_64"
  cp "$d/qemu-system-x86_64" "$d/qemu-system-aarch64"
  cat >"$d/qemu-img" <<'STUB'
#!/bin/sh
echo "qemu-img $*" >>"$STUB_LOG"
[ "$1" = resize ] && truncate -s "$5" "$4"
exit 0
STUB
  chmod +x "$d/qemu-system-x86_64" "$d/qemu-system-aarch64" "$d/qemu-img"
}
mkstubs "$hs"
# A PATH holding only the commands the runner needs, so no real QEMU is found.
for c in bash env paste stat find sort dirname tr cat; do ln -s "$(command -v "$c")" "$tools/$c"; done

# mksysroot <workdir> -> native QEMU stubs and a stub uninative loader, which
# logs its call and then execs the command after --library-path <dirs>.
mksysroot() {
  local d=$1 sr un
  sr=$d/build/tmp/sysroots-components/x86_64
  un=$d/build/tmp/sysroots-uninative/x86_64-linux/lib
  mkdir -p "$sr/qemu-system-native/usr/bin" "$sr/qemu-system-native/usr/lib" "$sr/glib-native/usr/lib" "$un"
  mkstubs "$sr/qemu-system-native/usr/bin"
  # shellcheck disable=SC2016 # $* and $@ belong to the generated stub
  printf '#!/bin/sh\necho "loader $*" >>"$STUB_LOG"\nshift 2\nexec "$@"\n' >"$un/ld-linux-x86-64.so.2"
  chmod +x "$un/ld-linux-x86-64.so.2"
}

# workdir <name> -> a fresh kas work directory holding build/tmp and both boot
# firmware images in the deploy output, printed. Firmware cases remove them.
workdir() {
  local d="$w/$1"
  mkdir -p "$d/build/tmp/deploy/stone/_build"
  : >"$d/build/tmp/deploy/stone/flash.bin"
  : >"$d/build/tmp/deploy/stone/u-boot.rom"
  echo "$d"
}
deploy() { echo "$1/build/tmp/deploy/stone/_build"; }

# run <dir> <args...> -> runs the runner from <dir>, stdout and stderr merged.
# RUNENV holds extra NAME=value words for env; runpath runs with a given PATH.
RUNENV=()
runpath() {
  local p=$1 d=$2
  shift 2
  (cd "$d" && env PATH="$p" "${RUNENV[@]}" bash "$script" "$@" </dev/null 2>&1)
}
run() { runpath "$hs:$PATH" "$@"; }

names_listed() { grep -q qemux86-64 <<<"$1" && grep -q qemuarm64 <<<"$1"; }

# 1. An unsupported name exits 2 and lists the supported names.
d=$(workdir unknown)
out=$(run "$d" qemuriscv --dry-run)
rc=$?
{ [ $rc -eq 2 ] && grep -qF "run-qemu: unsupported machine 'qemuriscv'" <<<"$out" && names_listed "$out"; } \
  && ok "an unsupported machine exits 2 and lists the supported names" || bad "unknown: rc=$rc out=[$out]"

# 2. No machine at all exits 2 and lists the names.
out=$(run "$d")
rc=$?
{ [ $rc -eq 2 ] && grep -qF "run-qemu: unsupported machine ''" <<<"$out" && names_listed "$out"; } \
  && ok "a missing machine exits 2 and lists the supported names" || bad "none: rc=$rc out=[$out]"

# 3. arm64-uefi-v9 is not a machine on this branch.
p="$(deploy "$d")"
truncate -s 1M "$p/avocado-os-avocado-arm64-uefi-v9.img"
out=$(run "$d" arm64-uefi-v9 --dry-run)
rc=$?
{ [ $rc -eq 2 ] && grep -qF "run-qemu: unsupported machine 'arm64-uefi-v9'" <<<"$out" && names_listed "$out" \
  && ! grep -q '^image:' <<<"$out"; } \
  && ok "arm64-uefi-v9 exits 2 as an unsupported machine" || bad "arm64-uefi-v9: rc=$rc out=[$out]"

# 4. An unknown option exits 2 naming it.
out=$(run "$d" qemux86-64 --frobnicate)
rc=$?
{ [ $rc -eq 2 ] && grep -qF "run-qemu: unknown option '--frobnicate'" <<<"$out"; } \
  && ok "an unknown option exits 2 naming it" || bad "option: rc=$rc out=[$out]"

# 5. --tpm with qemuarm64 exits 2 naming qemux86-64.
d=$(workdir tpm-other)
truncate -s 1M "$(deploy "$d")/avocado-os-avocado-qemuarm64.img"
out=$(run "$d" --tpm qemuarm64 --dry-run)
rc=$?
{ [ $rc -eq 2 ] && grep -qF "run-qemu: --tpm is only supported for qemux86-64" <<<"$out" && ! grep -q '^image:' <<<"$out"; } \
  && ok "--tpm with qemuarm64 exits 2 naming qemux86-64" || bad "tpm other: rc=$rc out=[$out]"

# 6. --tpm with qemux86-64 is accepted.
d=$(workdir tpm-x86)
img="$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
truncate -s 1M "$img"
out=$(run "$d" qemux86-64 --tpm --dry-run)
rc=$?
{ [ $rc -eq 0 ] && grep -qxF "image: $img" <<<"$out"; } \
  && ok "--tpm with qemux86-64 is accepted" || bad "tpm x86: rc=$rc out=[$out]"

# 7. The platform-named image wins over the machine-named and root-disk images.
d=$(workdir all-three)
p="$(deploy "$d")"
truncate -s 1M "$p/avocado-os-avocado-qemuarm64.img" "$p/avocado-os-qemuarm64.img" "$p/avocado-qemuarm64-rootdisk.img"
out=$(run "$d" qemuarm64 --dry-run)
rc=$?
{ [ $rc -eq 0 ] && grep -qxF "image: $p/avocado-os-avocado-qemuarm64.img" <<<"$out"; } \
  && ok "the platform-named image is preferred" || bad "platform: rc=$rc out=[$out]"

# 8. Only the platform-named image present is selected.
d=$(workdir platform-only)
p="$(deploy "$d")"
truncate -s 1M "$p/avocado-os-avocado-qemuarm64.img"
out=$(run "$d" qemuarm64 --dry-run)
rc=$?
{ [ $rc -eq 0 ] && grep -qxF "image: $p/avocado-os-avocado-qemuarm64.img" <<<"$out"; } \
  && ok "a lone platform-named image is selected" || bad "platform only: rc=$rc out=[$out]"

# 9. The machine-named image wins over the root-disk image.
d=$(workdir machine-named)
p="$(deploy "$d")"
truncate -s 1M "$p/avocado-os-qemux86-64.img" "$p/avocado-qemux86-64-rootdisk.img"
out=$(run "$d" qemux86-64 --dry-run)
rc=$?
{ [ $rc -eq 0 ] && grep -qxF "image: $p/avocado-os-qemux86-64.img" <<<"$out"; } \
  && ok "the machine-named image is preferred over the root disk" || bad "machine: rc=$rc out=[$out]"

# 10. The root-disk image is used when it is the only one.
d=$(workdir rootdisk)
p="$(deploy "$d")"
truncate -s 1M "$p/avocado-qemuarm64-rootdisk.img"
out=$(run "$d" qemuarm64 --dry-run)
rc=$?
{ [ $rc -eq 0 ] && grep -qxF "image: $p/avocado-qemuarm64-rootdisk.img" <<<"$out"; } \
  && ok "the root-disk image is the last fallback" || bad "rootdisk: rc=$rc out=[$out]"

# 11. Another machine's image does not satisfy the lookup; no image exits 1
#     naming the directory and all three names.
d=$(workdir no-image)
p="$(deploy "$d")"
truncate -s 1M "$p/avocado-os-avocado-qemux86-64.img"
out=$(run "$d" qemuarm64 --dry-run)
rc=$?
{ [ $rc -eq 1 ] && grep -qF "$p" <<<"$out" && grep -qF avocado-os-avocado-qemuarm64.img <<<"$out" \
  && grep -qF avocado-os-qemuarm64.img <<<"$out" && grep -qF avocado-qemuarm64-rootdisk.img <<<"$out" \
  && ! grep -q '^image:' <<<"$out"; } \
  && ok "no image exits 1 naming the directory and the three names" || bad "no image: rc=$rc out=[$out]"

# 12. Outside a work directory (no build/tmp) exits 1 naming build/tmp.
d="$w/bare"
mkdir -p "$d"
out=$(run "$d" qemux86-64 --dry-run)
rc=$?
{ [ $rc -eq 1 ] && grep -qF "no build output at $d/build/tmp" <<<"$out" && ! grep -q '^image:' <<<"$out"; } \
  && ok "no build/tmp exits 1 naming it" || bad "bare: rc=$rc out=[$out]"

# 13. --image replaces the lookup and needs no work directory.
c="$w/copied"
mkdir -p "$c"
truncate -s 1M "$c/disk.img"
RUNENV=(RUN_QEMU_FLASH_BIN="$c/flash.bin")
: >"$c/flash.bin"
out=$(run "$d" qemuarm64 --image "$c/disk.img" --dry-run)
rc=$?
RUNENV=()
{ [ $rc -eq 0 ] && grep -qxF "image: $c/disk.img" <<<"$out"; } \
  && ok "--image works outside a work directory" || bad "image path: rc=$rc out=[$out]"

# 14. --image wins over an image the lookup would have found.
d=$(workdir explicit-wins)
truncate -s 1M "$(deploy "$d")/avocado-os-avocado-qemuarm64.img"
out=$(run "$d" qemuarm64 --dry-run --image "$c/disk.img")
rc=$?
{ [ $rc -eq 0 ] && grep -qxF "image: $c/disk.img" <<<"$out"; } \
  && ok "--image replaces the work-directory lookup" || bad "image wins: rc=$rc out=[$out]"

# 15. A missing --image file exits 1 naming it.
out=$(run "$d" qemuarm64 --image "$c/absent.img" --dry-run)
rc=$?
{ [ $rc -eq 1 ] && grep -qF "$c/absent.img" <<<"$out" && ! grep -q '^image:' <<<"$out"; } \
  && ok "a missing --image file exits 1 naming it" || bad "absent image: rc=$rc out=[$out]"

# 16. --image with no value is a usage error, not a lookup.
out=$(run "$d" qemuarm64 --image)
rc=$?
{ [ $rc -eq 2 ] && ! grep -q '^image:' <<<"$out"; } \
  && ok "--image without a path exits 2" || bad "image no value: rc=$rc out=[$out]"

# 17. --image with an empty path exits 2.
out=$(run "$d" qemuarm64 --image "" --dry-run)
rc=$?
{ [ $rc -eq 2 ] && ! grep -q '^image:' <<<"$out"; } \
  && ok "--image with an empty path exits 2" || bad "image empty: rc=$rc out=[$out]"

# size_of <file> -> the file size in bytes.
size_of() { stat -c %s "$1"; }

# resize_case <name> <machine> <initial size> <expected MiB or none>
# Runs through --dry-run: the runner reports the size it would grow the image to
# and the image must be left untouched.
resize_case() {
  local name=$1 machine=$2 start=$3 want=$4 d i out rc before got q
  d=$(workdir "rs-$name")
  i="$(deploy "$d")/avocado-os-avocado-$machine.img"
  truncate -s "$start" "$i"
  before=$(size_of "$i")
  : >"$log"
  out=$(run "$d" "$machine" --dry-run)
  rc=$?
  got=$(size_of "$i")
  q="$hs/qemu-img resize -f raw $i ${want}M"
  if [ "$want" = none ]; then
    { [ $rc -eq 0 ] && [ "$got" -eq "$before" ] && grep -qxF 'resize: none' <<<"$out" && [ ! -s "$log" ]; } \
      && ok "$name: no resize" || bad "$name: rc=$rc out=[$out]"
  else
    { [ $rc -eq 0 ] && [ "$got" -eq "$before" ] && grep -qxF "resize: $q" <<<"$out" && [ ! -s "$log" ]; } \
      && ok "$name: $start grows to ${want}M, image untouched" || bad "$name: rc=$rc out=[$out]"
  fi
}

# 18. The resize rule, the same for both machines.
resize_case x86-600M qemux86-64 600M 1024
resize_case x86-1024M qemux86-64 1024M none
resize_case x86-1500M qemux86-64 1500M 2048
resize_case x86-2G qemux86-64 2G none
resize_case arm-600M qemuarm64 600M 1024
resize_case arm-1024M qemuarm64 1024M none
resize_case arm-1500M qemuarm64 1500M 2048
resize_case arm-2G qemuarm64 2G none
resize_case arm-3000M qemuarm64 3000M 4096

# 19. A symlinked image is measured at its target, not at the link.
d=$(workdir symlink)
p="$(deploy "$d")"
truncate -s 1500M "$c/big.img"
ln -s "$c/big.img" "$p/avocado-os-avocado-qemuarm64.img"
out=$(run "$d" qemuarm64 --dry-run)
rc=$?
{ [ $rc -eq 0 ] && grep -qxF "resize: $hs/qemu-img resize -f raw $p/avocado-os-avocado-qemuarm64.img 2048M" <<<"$out"; } \
  && ok "a symlinked 1500M image grows to 2048M" || bad "symlink: rc=$rc out=[$out]"

# cmdline <output> -> the text after "command: " on the one command line.
cmdline() { sed -n 's/^command: //p' <<<"$1"; }

# 20. A native QEMU is preferred over the host's, runs through the uninative
#     loader (uninative lib dir first, then every native lib dir) and gets -L
#     with its own data dir first.
d=$(workdir native)
mksysroot "$d"
img="$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
truncate -s 1M "$img"
sr=$d/build/tmp/sysroots-components/x86_64
un=$d/build/tmp/sysroots-uninative/x86_64-linux/lib
out=$(run "$d" qemux86-64 --dry-run)
rc=$?
c=$(cmdline "$out")
want="$un/ld-linux-x86-64.so.2 --library-path $un:$sr/glib-native/usr/lib:$sr/qemu-system-native/usr/lib $sr/qemu-system-native/usr/bin/qemu-system-x86_64 -L $sr/qemu-system-native/usr/share/qemu -bios "
{ [ $rc -eq 0 ] && grep -qxF 'qemu: qemu-system-x86_64' <<<"$out" && [[ $c == "$want"* ]] \
  && grep -qxF "resize: $un/ld-linux-x86-64.so.2 --library-path $un:$sr/glib-native/usr/lib:$sr/qemu-system-native/usr/lib $sr/qemu-system-native/usr/bin/qemu-img resize -f raw $img 1024M" <<<"$out"; } \
  && ok "a native QEMU is selected and runs through the uninative loader" || bad "native: rc=$rc out=[$out]"

# 21. The native resize and launch really go through the loader.
: >"$log"
out=$(run "$d" qemux86-64)
rc=$?
{ [ $rc -eq 0 ] && [ "$(grep -c '^loader ' "$log")" -eq 2 ] && grep -q '^qemu-launch -L ' "$log" \
  && [ "$(size_of "$img")" -eq $((1024 * 1048576)) ]; } \
  && ok "a native real run resizes and launches under the loader" || bad "native run: rc=$rc out=[$out] log=[$(cat "$log")]"

# 22. With no native QEMU the host's from PATH is used, without -L.
d=$(workdir host)
img="$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
truncate -s 1M "$img"
out=$(run "$d" qemux86-64 --dry-run)
rc=$?
c=$(cmdline "$out")
{ [ $rc -eq 0 ] && grep -qxF 'qemu: qemu-system-x86_64' <<<"$out" && [[ $c == "$hs/qemu-system-x86_64 -bios "* ]] \
  && [[ $c != *" -L "* ]]; } \
  && ok "the host QEMU is used when there is no native one" || bad "host: rc=$rc out=[$out]"

# 23. Neither a native nor a host QEMU exits 1 naming both places.
out=$(runpath "$tools" "$d" qemux86-64 --dry-run)
rc=$?
{ [ $rc -eq 1 ] && grep -qF "$d/build/tmp/sysroots-components/x86_64/qemu-system-native/usr/bin/qemu-system-x86_64" <<<"$out" \
  && grep -qF 'none on PATH' <<<"$out" && ! grep -q '^command:' <<<"$out"; } \
  && ok "no QEMU anywhere exits 1 naming both places" || bad "no qemu: rc=$rc out=[$out]"

# 24. Native QEMU without the uninative loader exits 1 naming the loader.
d=$(workdir no-loader)
mksysroot "$d"
rm "$d/build/tmp/sysroots-uninative/x86_64-linux/lib/ld-linux-x86-64.so.2"
truncate -s 1M "$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
out=$(run "$d" qemux86-64 --dry-run)
rc=$?
{ [ $rc -eq 1 ] && grep -qF ld-linux-x86-64.so.2 <<<"$out" && ! grep -q '^command:' <<<"$out"; } \
  && ok "a missing uninative loader exits 1 naming it" || bad "no loader: rc=$rc out=[$out]"

# fwcase <name> <machine> <image-name> <placement> -> workdir with the firmware
# image only at <placement> (stone, build, none); prints the dry-run output.
fwdir() {
  local name=$1 machine=$2 fw=$3 where=$4 d
  d=$(workdir "$name")
  rm -f "$d/build/tmp/deploy/stone/flash.bin" "$d/build/tmp/deploy/stone/u-boot.rom"
  truncate -s 1M "$(deploy "$d")/avocado-os-avocado-$machine.img"
  case $where in
    stone) : >"$d/build/tmp/deploy/stone/$fw" ;;
    build) : >"$d/build/tmp/deploy/stone/_build/$fw" ;;
    both)
      echo new >"$d/build/tmp/deploy/stone/$fw"
      echo old >"$d/build/tmp/deploy/stone/_build/$fw"
      ;;
  esac
  echo "$d"
}

# 25. Firmware lookup: deploy output, older subdirectory, deploy output first.
for spec in "qemux86-64 u-boot.rom" "qemuarm64 flash.bin"; do
  read -r m fw <<<"$spec"
  d=$(fwdir "fw-stone-$m" "$m" "$fw" stone)
  out=$(run "$d" "$m" --dry-run)
  rc=$?
  { [ $rc -eq 0 ] && grep -qF " -bios $d/build/tmp/deploy/stone/$fw " <<<"$out"; } \
    && ok "$m: $fw is found in the deploy output" || bad "$m stone: rc=$rc out=[$out]"
  d=$(fwdir "fw-build-$m" "$m" "$fw" build)
  out=$(run "$d" "$m" --dry-run)
  rc=$?
  { [ $rc -eq 0 ] && grep -qF " -bios $d/build/tmp/deploy/stone/_build/$fw " <<<"$out"; } \
    && ok "$m: $fw is found in the older _build subdirectory" || bad "$m build: rc=$rc out=[$out]"
  d=$(fwdir "fw-both-$m" "$m" "$fw" both)
  out=$(run "$d" "$m" --dry-run)
  rc=$?
  { [ $rc -eq 0 ] && grep -qF " -bios $d/build/tmp/deploy/stone/$fw " <<<"$out"; } \
    && ok "$m: the deploy output wins over _build" || bad "$m both: rc=$rc out=[$out]"
done

# 26. Overrides: RUN_QEMU_UBOOT_ROM for x86, RUN_QEMU_FLASH_BIN for arm64; each
#     wins over the deploy output, and a missing file exits 1 naming both.
for spec in "qemux86-64 u-boot.rom RUN_QEMU_UBOOT_ROM" "qemuarm64 flash.bin RUN_QEMU_FLASH_BIN"; do
  read -r m fw var <<<"$spec"
  d=$(fwdir "fw-ovr-$m" "$m" "$fw" stone)
  : >"$w/custom-$fw"
  RUNENV=("$var=$w/custom-$fw")
  out=$(run "$d" "$m" --dry-run)
  rc=$?
  { [ $rc -eq 0 ] && grep -qF " -bios $w/custom-$fw " <<<"$out"; } \
    && ok "$m: $var overrides the lookup" || bad "$m override: rc=$rc out=[$out]"
  RUNENV=("$var=$w/absent-$fw")
  out=$(run "$d" "$m" --dry-run)
  rc=$?
  RUNENV=()
  { [ $rc -eq 1 ] && grep -qF "$var" <<<"$out" && grep -qF "$w/absent-$fw" <<<"$out" && ! grep -q '^command:' <<<"$out"; } \
    && ok "$m: $var naming a missing file exits 1 naming both" || bad "$m override missing: rc=$rc out=[$out]"
  d=$(fwdir "fw-none-$m" "$m" "$fw" none)
  out=$(run "$d" "$m" --dry-run)
  rc=$?
  { [ $rc -eq 1 ] && grep -qF "$d/build/tmp/deploy/stone/$fw" <<<"$out" && grep -qF "$d/build/tmp/deploy/stone/_build/$fw" <<<"$out" \
    && ! grep -q '^command:' <<<"$out"; } \
    && ok "$m: no $fw anywhere exits 1 listing both locations" || bad "$m none: rc=$rc out=[$out]"
  : >"$log"
  out=$(run "$d" "$m")
  rc=$?
  { [ $rc -eq 1 ] && ! grep -q qemu-launch "$log"; } \
    && ok "$m: a missing $fw never reaches QEMU" || bad "$m none run: rc=$rc log=[$(cat "$log")]"
done

# 27. The exact command lines.
d=$(workdir cmd-x86)
img="$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
truncate -s 1M "$img"
out=$(run "$d" qemux86-64 --dry-run)
rc=$?
want="$hs/qemu-system-x86_64 -bios $d/build/tmp/deploy/stone/u-boot.rom -device sdhci-pci -device sd-card,drive=mmc -drive file=$img,if=none,format=raw,id=mmc -m 256 -cpu max -nographic"
{ [ $rc -eq 0 ] && [ "$(grep -c '^command: ' <<<"$out")" -eq 1 ] && [ "$(cmdline "$out")" = "$want" ] \
  && ! grep -qE 'pflash|edk2' <<<"$out"; } \
  && ok "the qemux86-64 command line is exact and has no pflash" || bad "cmd x86: rc=$rc out=[$out] want=[$want]"

d=$(workdir cmd-arm)
img="$(deploy "$d")/avocado-os-avocado-qemuarm64.img"
truncate -s 1M "$img"
out=$(run "$d" qemuarm64 --dry-run)
rc=$?
want="$hs/qemu-system-aarch64 -M virt,secure=on,highmem=off,acpi=off -cpu cortex-a53 -m 1024 -bios $d/build/tmp/deploy/stone/flash.bin -device sdhci-pci -device sd-card,drive=mmc -drive file=$img,if=none,format=raw,id=mmc -nographic"
{ [ $rc -eq 0 ] && [ "$(cmdline "$out")" = "$want" ] && grep -q 'secure=on' <<<"$out" && ! grep -qE 'pflash|edk2' <<<"$out" \
  && grep -qxF 'qemu: qemu-system-aarch64' <<<"$out"; } \
  && ok "the qemuarm64 command line is exact and has secure=on" || bad "cmd arm: rc=$rc out=[$out] want=[$want]"

# 28. Commas in the image path are doubled so QEMU reads them literally.
d=$(workdir commas)
mkdir -p "$w/a,b"
truncate -s 1M "$w/a,b/disk.img"
out=$(run "$d" qemuarm64 --image "$w/a,b/disk.img" --dry-run)
rc=$?
{ [ $rc -eq 0 ] && grep -qF -- "-drive file=$w/a,,b/disk.img,if=none" <<<"$out" && grep -qxF "image: $w/a,b/disk.img" <<<"$out"; } \
  && ok "commas in the image path are doubled" || bad "commas: rc=$rc out=[$out]"

# 29. A stubbed real run starts QEMU as a child, passes its exit status through
#     and leaves no variable-store file beside the image.
for m in qemux86-64 qemuarm64; do
  d=$(workdir "real-$m")
  i="$(deploy "$d")/avocado-os-avocado-$m.img"
  truncate -s 600M "$i"
  : >"$log"
  RUNENV=(STUB_QEMU_RC=7)
  out=$(run "$d" "$m")
  rc=$?
  RUNENV=()
  n=$(find "$(deploy "$d")" -mindepth 1 | wc -l)
  { [ $rc -eq 7 ] && grep -q "^qemu-img resize -f raw $i 1024M\$" "$log" && grep -q '^qemu-launch ' "$log" \
    && [ "$n" -eq 1 ] && [ "$(size_of "$i")" -eq $((1024 * 1048576)) ]; } \
    && ok "$m: a real run resizes, passes QEMU's status through and makes no variable store" \
    || bad "$m real: rc=$rc n=$n out=[$out] log=[$(cat "$log")]"
done

echo "passed: $pass  failed: $fail"
[ "$fail" -eq 0 ]
