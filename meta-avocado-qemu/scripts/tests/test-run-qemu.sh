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

# --- --tpm: swtpm lifecycle -------------------------------------------------
# swtpm is a python3 stub that daemonizes like the real one (--daemon, --pid
# file=), then either binds the --ctrl socket (mode sock) or never does (nosock).
# The runs use PATH = the stubs plus coreutils only, so no real swtpm or QEMU is
# needed, and the stub QEMU either exits at once or sleeps.
for c in mktemp sleep cp mv chmod rm mkdir rmdir truncate seq; do ln -s "$(command -v "$c")" "$tools/$c" 2>/dev/null; done
mkswtpm() {
  local d=$1 mode=$2
  mkdir -p "$d"
  {
    echo "#!$(command -v python3)"
    echo "MODE = '$mode'"
    cat <<'EOF'
import os, socket, sys, time
args = sys.argv[1:]
ctrl = pidfile = None
for i, a in enumerate(args):
    if a.startswith("type=unixio,path="):
        ctrl = a.split("path=", 1)[1]
    if a.startswith("file=") and args[i - 1] == "--pid":
        pidfile = a[5:]
with open(os.environ["STUB_LOG"], "a") as f:
    f.write("swtpm " + " ".join(args) + "\n")
if "--daemon" in args:
    pid = os.fork()
    if pid:
        with open(pidfile, "w") as f:
            f.write("%d\n" % pid)
        with open(os.environ["STUB_LOG"], "a") as f:
            f.write("swtpm-pid %d\n" % pid)
        sys.exit(0)
    os.setsid()
    null = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(null, fd)
if MODE == "sock":
    s = socket.socket(socket.AF_UNIX)
    s.bind(ctrl)
    s.listen(1)
time.sleep(60)
EOF
  } >"$d/swtpm"
  chmod +x "$d/swtpm"
}
tpmhs=$w/tpmstubs
nosockhs=$w/nosockstubs
sleephs=$w/sleepstubs
failhs=$w/tpmfailstubs
noswtpmhs=$w/noswtpmstubs
mkdir -p "$tpmhs" "$nosockhs" "$sleephs" "$failhs" "$noswtpmhs"
mkstubs "$tpmhs"
mkswtpm "$tpmhs" sock
mkstubs "$nosockhs"
mkswtpm "$nosockhs" nosock
mkstubs "$sleephs"
mkswtpm "$sleephs" sock
# shellcheck disable=SC2016 # $* belongs to the generated stub
printf '#!/bin/sh\necho "qemu-launch $*" >>"$STUB_LOG"\nsleep 30\n' >"$sleephs/qemu-system-x86_64"
mkstubs "$failhs"
mkswtpm "$failhs" sock
printf '#!/bin/sh\nexit 7\n' >"$failhs/qemu-system-x86_64"
mkstubs "$noswtpmhs"

# alive <pid> -> true for a running process; a zombie is already dead.
alive() {
  local s
  [ -r "/proc/$1/stat" ] || return 1
  s=$(<"/proc/$1/stat")
  s=${s##*) }
  [ "${s%% *}" != Z ]
}
# trun <dir> <args...> -> like run, but PATH is $TPMSTUBS plus the coreutils.
trun() {
  local d=$1
  shift
  (cd "$d" && env PATH="${TPMSTUBS-$tpmhs}:$tools" RUN_QEMU_HOST_QEMU_DATA_DIR="$w/hostdata" \
    RUN_QEMU_TPM_WAIT_SECONDS="${TPMWAIT-3}" TMPDIR="${TPMTMP-$w}" bash "$script" "$@" </dev/null 2>&1)
}
tpm_args_in() { grep -qF -- "-chardev socket,id=chrtpm,path=$2 -tpmdev emulator,id=tpm0,chardev=chrtpm -device tpm-tis,tpmdev=tpm0" <<<"$1"; }

# 33. --dry-run with --tpm prints the TPM arguments and starts and creates nothing.
d=$(workdir tpm-dry)
truncate -s 2G "$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
: >"$log"
out=$(trun "$d" qemux86-64 --tpm --dry-run)
rc=$?
sock=$(sed -n 's/^tpm: socket //p' <<<"$out")
{ [ $rc -eq 0 ] && [ -n "$sock" ] && [ "${#sock}" -lt 100 ] && [[ $sock == "$w"/run-qemu-tpmsock.*/swtpm-sock ]] \
  && tpm_args_in "$(cmdline "$out")" "$sock" && [ ! -s "$log" ] && [ ! -e "$d/build/tmp/tpm-state" ] \
  && [ -z "$(ls -d "$w"/run-qemu-tpmsock.* 2>/dev/null)" ]; } \
  && ok "--tpm --dry-run prints the TPM arguments and starts and creates nothing" || bad "tpm dry: rc=$rc out=[$out] log=[$(cat "$log")]"

# 34. A normal run starts swtpm before QEMU, wires it in, and leaves no swtpm behind.
d=$(workdir tpm-run)
truncate -s 2G "$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
: >"$log"
out=$(trun "$d" qemux86-64 --tpm)
rc=$?
sd="$d/build/tmp/tpm-state"
tl=$(grep '^swtpm socket' "$log")
sock=$(sed -n 's/.*--ctrl type=unixio,path=\([^ ]*\).*/\1/p' <<<"$tl")
pid=$(sed -n 's/^swtpm-pid //p' "$log")
st=$(grep -n '^swtpm socket' "$log" | head -1 | cut -d: -f1)
ql=$(grep -n '^qemu-launch' "$log" | head -1 | cut -d: -f1)
{ [ $rc -eq 0 ] && [ -n "$sock" ] && [ "${#sock}" -lt 100 ] && [ -n "$pid" ] && ! alive "$pid" && [ -n "$st" ] && [ -n "$ql" ] && [ "$st" -lt "$ql" ] \
  && grep -qF -- "--tpmstate dir=$sd" <<<"$tl" && [[ $sock == "$w"/run-qemu-tpmsock.*/swtpm-sock ]] \
  && grep -qF -- '--tpm2' <<<"$tl" && grep -qF -- '--daemon' <<<"$tl" && grep -qF -- "--pid file=$sd/swtpm.pid" <<<"$tl" \
  && tpm_args_in "$(grep '^qemu-launch' "$log")" "$sock" && [ ! -e "$sock" ] && [ ! -e "$(dirname "$sock")" ] && [ ! -e "$sd/swtpm.pid" ]; } \
  && ok "a normal --tpm run starts swtpm first, wires it in and stops it" || bad "tpm run: rc=$rc pid=$pid out=[$out] log=[$(cat "$log")]"

# 35. A group TERM while QEMU runs still stops swtpm.
d=$(workdir tpm-term)
truncate -s 2G "$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
: >"$log"
(cd "$d" && exec setsid env PATH="$sleephs:$tools" RUN_QEMU_HOST_QEMU_DATA_DIR="$w/hostdata" \
  RUN_QEMU_TPM_WAIT_SECONDS=3 TMPDIR="$w" bash "$script" qemux86-64 --tpm >"$w/term.out" 2>&1 </dev/null) &
rp=$!
for _ in $(seq 1 100); do
  grep -q '^qemu-launch' "$log" && break
  sleep 0.1
done
pid=$(sed -n 's/^swtpm-pid //p' "$log")
rc=none
if [ "$(ps -o pgid= -p "$rp" | tr -d ' ')" = "$rp" ] && grep -q '^qemu-launch' "$log"; then
  kill -TERM -- "-$rp"
  wait "$rp"
  rc=$?
fi
{ [ "$rc" = 143 ] && [ -n "$pid" ] && ! alive "$pid" && [ ! -e "$d/build/tmp/tpm-state/swtpm.pid" ]; } \
  && ok "a TERM while QEMU runs stops swtpm" || bad "tpm term: rc=$rc pid=$pid out=[$(cat "$w/term.out")] log=[$(cat "$log")]"
if [ -n "$pid" ] && alive "$pid"; then kill "$pid" 2>/dev/null; fi

# 36. A socket that never appears exits 1 naming it, never starts QEMU, and stops swtpm.
d=$(workdir tpm-nosock)
truncate -s 2G "$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
: >"$log"
out=$(TPMSTUBS=$nosockhs TPMWAIT=1 trun "$d" qemux86-64 --tpm)
rc=$?
sock=$(sed -n 's/.*--ctrl type=unixio,path=\([^ ]*\).*/\1/p' "$log")
pid=$(sed -n 's/^swtpm-pid //p' "$log")
{ [ $rc -eq 1 ] && [ -n "$sock" ] && grep -qF "$sock" <<<"$out" && [ ! -e "$(dirname "$sock")" ] && grep -qi 'qemu was not started' <<<"$out" && ! grep -q '^qemu-launch' "$log" \
  && [ -n "$pid" ] && ! alive "$pid"; } \
  && ok "a missing TPM socket exits 1 naming it, without starting QEMU" || bad "tpm nosock: rc=$rc pid=$pid out=[$out] log=[$(cat "$log")]"
if [ -n "$pid" ] && alive "$pid"; then kill "$pid" 2>/dev/null; fi

# 37. With no build directory the state dir is a temp dir, removed on exit.
mkdir -p "$w/tmpd" "$w/bare-tpm"
truncate -s 1100M "$w/bare-tpm/disk.img"
: >"$w/bare-tpm/u-boot.rom"
: >"$log"
out=$(RUN_QEMU_UBOOT_ROM=$w/bare-tpm/u-boot.rom TPMTMP=$w/tmpd trun "$w/bare-tpm" qemux86-64 --tpm --image "$w/bare-tpm/disk.img")
rc=$?
pid=$(sed -n 's/^swtpm-pid //p' "$log")
{ [ $rc -eq 0 ] && grep -qF -- "path=$w/tmpd/" "$log" && [ -z "$(ls -A "$w/tmpd")" ] && [ -n "$pid" ] && ! alive "$pid" \
  && [ ! -e "$w/bare-tpm/build" ]; } \
  && ok "without a build dir the TPM state is a temp dir removed on exit" || bad "tpm tmp: rc=$rc out=[$out] left=[$(ls -A "$w/tmpd")] log=[$(cat "$log")]"

# 38. The QEMU exit status passes through and swtpm is still stopped.
d=$(workdir tpm-fail)
truncate -s 2G "$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
: >"$log"
out=$(TPMSTUBS=$failhs trun "$d" qemux86-64 --tpm)
rc=$?
pid=$(sed -n 's/^swtpm-pid //p' "$log")
{ [ $rc -eq 7 ] && [ -n "$pid" ] && ! alive "$pid"; } \
  && ok "the QEMU exit status passes through and swtpm is stopped" || bad "tpm fail: rc=$rc pid=$pid out=[$out]"

# 39. A native swtpm runs through the uninative loader in preference to the host's.
d=$(workdir tpm-native)
mksysroot "$d"
sr="$d/build/tmp/sysroots-components/x86_64"
mkswtpm "$sr/swtpm-native/usr/bin" sock
truncate -s 2G "$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
: >"$log"
out=$(TPMSTUBS=$noswtpmhs trun "$d" qemux86-64 --tpm)
rc=$?
pid=$(sed -n 's/^swtpm-pid //p' "$log")
{ [ $rc -eq 0 ] && grep -q "^loader --library-path .* $sr/swtpm-native/usr/bin/swtpm socket " "$log" && [ -n "$pid" ] && ! alive "$pid"; } \
  && ok "a native swtpm runs under the uninative loader" || bad "tpm native: rc=$rc pid=$pid out=[$out] log=[$(cat "$log")]"

# 40. No swtpm native or on PATH exits 1 naming where it looked, before QEMU starts.
d=$(workdir tpm-noswtpm)
truncate -s 2G "$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
: >"$log"
out=$(TPMSTUBS=$noswtpmhs trun "$d" qemux86-64 --tpm)
rc=$?
{ [ $rc -eq 1 ] && grep -qF "$d/build/tmp/sysroots-components/x86_64/swtpm-native/usr/bin/swtpm" <<<"$out" \
  && ! grep -q '^qemu-launch' "$log"; } \
  && ok "no swtpm anywhere exits 1 naming where it looked" || bad "tpm none: rc=$rc out=[$out]"

# 41. A deliberately long work directory still works: the socket is short and
# lives outside it, because an AF_UNIX path holds only about 107 bytes.
longd="$w/tpm-long/$(printf 'long-directory-name-%.0s' 1 2 3 4 5 6)/work"
mkdir -p "$longd/build/tmp/deploy/stone/_build"
echo rom >"$longd/build/tmp/deploy/stone/u-boot.rom"
truncate -s 2G "$longd/build/tmp/deploy/stone/_build/avocado-os-avocado-qemux86-64.img"
: >"$log"
out=$(trun "$longd" qemux86-64 --tpm)
rc=$?
sock=$(sed -n 's/.*--ctrl type=unixio,path=\([^ ]*\).*/\1/p' "$log")
pid=$(sed -n 's/^swtpm-pid //p' "$log")
{ [ ${#longd} -gt 120 ] && [ $rc -eq 0 ] && [ -n "$sock" ] && [ ${#sock} -lt 100 ] && [[ $sock != "$longd"* ]] \
  && tpm_args_in "$(grep '^qemu-launch' "$log")" "$sock" && [ -n "$pid" ] && ! alive "$pid"; } \
  && ok "a long work directory still gets a short TPM socket outside it" || bad "tpm long: rc=$rc len=${#longd} sock=[$sock] out=[$out]"

# 42. The temp socket dir is removed after a TERM while QEMU runs.
d=$(workdir tpm-term2)
truncate -s 2G "$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
mkdir -p "$w/termtmp"
: >"$log"
(cd "$d" && exec setsid env PATH="$sleephs:$tools" RUN_QEMU_HOST_QEMU_DATA_DIR="$w/hostdata" \
  RUN_QEMU_TPM_WAIT_SECONDS=3 TMPDIR="$w/termtmp" bash "$script" qemux86-64 --tpm >"$w/term2.out" 2>&1 </dev/null) &
rp=$!
for _ in $(seq 1 100); do
  grep -q '^qemu-launch' "$log" && break
  sleep 0.1
done
pid=$(sed -n 's/^swtpm-pid //p' "$log")
existed=$(ls -A "$w/termtmp")
rc=none
if [ "$(ps -o pgid= -p "$rp" | tr -d ' ')" = "$rp" ] && grep -q '^qemu-launch' "$log"; then
  kill -TERM -- "-$rp"
  wait "$rp"
  rc=$?
fi
{ [ "$rc" = 143 ] && [ -n "$existed" ] && [ -z "$(ls -A "$w/termtmp")" ] && [ -n "$pid" ] && ! alive "$pid"; } \
  && ok "the temp TPM socket dir is removed after a TERM" || bad "tpm term2: rc=$rc existed=[$existed] left=[$(ls -A "$w/termtmp")] out=[$(cat "$w/term2.out")]"
if [ -n "$pid" ] && alive "$pid"; then kill "$pid" 2>/dev/null; fi

# 43. RUN_QEMU_TPM_SOCK_DIR names where the socket goes; the dir itself stays.
d=$(workdir tpm-override)
truncate -s 2G "$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
mkdir -p "$w/ovr" "$w/ovrtmp"
: >"$log"
out=$(RUN_QEMU_TPM_SOCK_DIR=$w/ovr TPMTMP=$w/ovrtmp trun "$d" qemux86-64 --tpm)
rc=$?
pid=$(sed -n 's/^swtpm-pid //p' "$log")
{ [ $rc -eq 0 ] && grep -qF -- "--ctrl type=unixio,path=$w/ovr/swtpm-sock" "$log" && tpm_args_in "$(grep '^qemu-launch' "$log")" "$w/ovr/swtpm-sock" \
  && [ -d "$w/ovr" ] && [ ! -e "$w/ovr/swtpm-sock" ] && [ -z "$(ls -A "$w/ovrtmp")" ] && [ -n "$pid" ] && ! alive "$pid"; } \
  && ok "RUN_QEMU_TPM_SOCK_DIR places the socket and is left in place" || bad "tpm override: rc=$rc out=[$out] log=[$(cat "$log")]"

# 44. An override that makes the socket path over 100 bytes exits 1 naming it, before swtpm.
d=$(workdir tpm-overlong)
truncate -s 2G "$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
longo="$w/$(printf 'o%.0s' $(seq 1 95))"
: >"$log"
out=$(RUN_QEMU_TPM_SOCK_DIR=$longo trun "$d" qemux86-64 --tpm)
rc=$?
{ [ $rc -eq 1 ] && grep -qF "$longo/swtpm-sock" <<<"$out" && grep -qE "$((${#longo} + 11))" <<<"$out" \
  && ! grep -q '^swtpm ' "$log" && ! grep -q '^qemu-launch' "$log" && [ ! -e "$longo" ]; } \
  && ok "a too-long socket path exits 1 naming it and its length, starting nothing" || bad "tpm overlong: rc=$rc out=[$out] log=[$(cat "$log")]"

# 45. A live swtpm already on the state dir stops the run, and is left alone.
d=$(workdir tpm-held)
truncate -s 2G "$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
sd=$d/build/tmp/tpm-state
mkdir -p "$sd"
# A holder with no child process: `read -t` on a fifo it opens read-write waits without
# forking, so killing the one pid leaves nothing holding the suite's stdout open.
mkfifo "$w/hold-a.fifo"
bash -c 'read -t 60 x <>"$1"; :' "swtpm socket --tpmstate dir=$sd" "$w/hold-a.fifo" &
holder=$!
echo "$holder" >"$sd/swtpm.pid"
: >"$log"
out=$(trun "$d" qemux86-64 --tpm)
rc=$?
{ [ $rc -eq 1 ] && grep -qF "already running" <<<"$out" && grep -qF "$holder" <<<"$out" && alive "$holder" \
  && [ "$(<"$sd/swtpm.pid")" = "$holder" ] && ! grep -q '^swtpm ' "$log" && ! grep -q '^qemu-launch' "$log"; } \
  && ok "a live swtpm on the state dir stops the run and keeps its pid file" || bad "tpm held: rc=$rc holder=$holder out=[$out] log=[$(cat "$log")]"
kill "$holder" 2>/dev/null
wait "$holder" 2>/dev/null

# 46. A pid file naming a process that is not swtpm on this state dir is stale and replaced.
d=$(workdir tpm-stale)
truncate -s 2G "$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
sd=$d/build/tmp/tpm-state
mkdir -p "$sd"
mkfifo "$w/hold-b.fifo"
bash -c 'read -t 60 x <>"$1"; :' "unrelated process" "$w/hold-b.fifo" &
other=$!
echo "$other" >"$sd/swtpm.pid"
: >"$log"
out=$(trun "$d" qemux86-64 --tpm)
rc=$?
pid=$(sed -n 's/^swtpm-pid //p' "$log")
{ [ $rc -eq 0 ] && alive "$other" && [ -n "$pid" ] && [ "$pid" != "$other" ] && ! alive "$pid"; } \
  && ok "a pid file naming an unrelated process is replaced, not obeyed" || bad "tpm stale: rc=$rc other=$other pid=$pid out=[$out]"
kill "$other" 2>/dev/null
wait "$other" 2>/dev/null

# 47. A comma in the socket directory is doubled in the chardev path, so it cannot add chardev options.
d=$(workdir tpm-comma)
truncate -s 2G "$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
mkdir -p "$w/c,d"
: >"$log"
out=$(RUN_QEMU_TPM_SOCK_DIR=$w/c,d trun "$d" qemux86-64 --tpm)
rc=$?
pid=$(sed -n 's/^swtpm-pid //p' "$log")
ql=$(grep '^qemu-launch' "$log")
{ [ $rc -eq 0 ] && grep -qF -- "path=$w/c,,d/swtpm-sock -tpmdev" <<<"$ql" && ! grep -qF -- "path=$w/c,d/swtpm-sock" <<<"$ql" \
  && [ -n "$pid" ] && ! alive "$pid"; } \
  && ok "a comma in the socket directory is doubled in the chardev path" || bad "tpm comma: rc=$rc out=[$out] ql=[$ql]"

# No stub swtpm may outlive the suite.
stray=$(pgrep -af "$w/.*swtpm" || true)
[ -z "$stray" ] && ok "no stub swtpm survives" || bad "stray swtpm: [$stray]"

echo "passed: $pass  failed: $fail"
[ "$fail" -eq 0 ]
