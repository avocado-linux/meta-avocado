#!/usr/bin/env bash
# Host test for run-qemu: machine naming, the TPM restriction, the image lookup
# under build/tmp/deploy/stone/_build and the explicit --image path. Every case
# runs in its own temp work directory through --dry-run, so no QEMU starts.
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
  printf '#!/bin/sh\necho "qemu-launch $*" >>"$STUB_LOG"\n' >"$d/qemu-system-x86_64"
  cp "$d/qemu-system-x86_64" "$d/qemu-system-aarch64"
  cat >"$d/qemu-img" <<'EOF'
#!/bin/sh
echo "qemu-img $*" >>"$STUB_LOG"
[ "$1" = resize ] && truncate -s "$5" "$4"
exit 0
EOF
  chmod +x "$d/qemu-system-x86_64" "$d/qemu-system-aarch64" "$d/qemu-img"
}
mkstubs "$hs"
# A PATH holding only the commands the runner needs, so no real QEMU is found.
for c in bash env paste stat find sort dirname tr cat; do ln -s "$(command -v "$c")" "$tools/$c"; done

# Hermetic firmware: RUN_QEMU_FIRMWARE_DIRS replaces the host list, so the runner
# never reads the real /usr/share. $fwdefault holds x86 and arm64 host firmware;
# a case overrides FWDIRS (even to the empty string). RUN_QEMU_HOST_QEMU_DATA_DIR
# stands in for the host QEMU's /usr/share/qemu.
fwdefault=$w/fw-default
mkdir -p "$fwdefault" "$w/hostdata"
for f in OVMF_CODE.fd OVMF_VARS.fd AAVMF_CODE.fd AAVMF_VARS.fd; do echo "default-$f" >"$fwdefault/$f"; done
unset FWDIRS

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

# workdir <name> -> a fresh kas work directory holding build/tmp, printed.
workdir() {
  local d="$w/$1"
  mkdir -p "$d/build/tmp/deploy/stone/_build"
  echo flash >"$d/build/tmp/deploy/stone/flash.bin"
  echo "$d"
}
deploy() { echo "$1/build/tmp/deploy/stone/_build"; }

# run <dir> <args...> -> runs the runner from <dir>, stdout and stderr merged.
run() {
  local d=$1
  shift
  (cd "$d" && env PATH="$hs:$PATH" RUN_QEMU_FIRMWARE_DIRS="${FWDIRS-$fwdefault}" \
    RUN_QEMU_HOST_QEMU_DATA_DIR="${HOSTDATA-$w/hostdata}" bash "$script" "$@" </dev/null 2>&1)
}

names_listed() { grep -q qemux86-64 <<<"$1" && grep -q qemuarm64 <<<"$1" && grep -q arm64-uefi-v9 <<<"$1"; }

# 1. An unsupported name exits 2 and lists the three supported names.
d=$(workdir unknown)
out=$(run "$d" qemuriscv --dry-run)
rc=$?
{ [ $rc -eq 2 ] && grep -qF "run-qemu: unsupported machine 'qemuriscv'" <<<"$out" && names_listed "$out"; } \
  && ok "an unsupported machine exits 2 and lists the supported names" || bad "unknown: rc=$rc out=[$out]"

# 2. No machine at all exits 2 and lists the three names.
out=$(run "$d")
rc=$?
{ [ $rc -eq 2 ] && grep -qF "run-qemu: unsupported machine ''" <<<"$out" && names_listed "$out"; } \
  && ok "a missing machine exits 2 and lists the supported names" || bad "none: rc=$rc out=[$out]"

# 3. An unknown option exits 2 naming it.
out=$(run "$d" qemux86-64 --frobnicate)
rc=$?
{ [ $rc -eq 2 ] && grep -qF "run-qemu: unknown option '--frobnicate'" <<<"$out"; } \
  && ok "an unknown option exits 2 naming it" || bad "option: rc=$rc out=[$out]"

# 4. --tpm with a machine other than qemux86-64 exits 2, for both other machines.
d=$(workdir tpm-other)
truncate -s 1M "$(deploy "$d")/avocado-os-avocado-arm64-uefi-v9.img" "$(deploy "$d")/avocado-os-avocado-qemuarm64.img"
out=$(run "$d" arm64-uefi-v9 --tpm --dry-run)
rc=$?
out2=$(run "$d" --tpm qemuarm64 --dry-run)
rc2=$?
{ [ $rc -eq 2 ] && [ $rc2 -eq 2 ] && grep -qF "run-qemu: --tpm is only supported for qemux86-64" <<<"$out" \
  && grep -qF "run-qemu: --tpm is only supported for qemux86-64" <<<"$out2" && ! grep -q '^image:' <<<"$out$out2"; } \
  && ok "--tpm with another machine exits 2 naming qemux86-64" || bad "tpm other: rc=$rc/$rc2 out=[$out][$out2]"

# 5. --tpm with qemux86-64 is accepted.
d=$(workdir tpm-x86)
img="$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
truncate -s 1M "$img"
out=$(run "$d" qemux86-64 --tpm --dry-run)
rc=$?
{ [ $rc -eq 0 ] && grep -qxF "image: $img" <<<"$out"; } \
  && ok "--tpm with qemux86-64 is accepted" || bad "tpm x86: rc=$rc out=[$out]"

# 6. The platform-named image wins over the machine-named and root-disk images.
d=$(workdir all-three)
p="$(deploy "$d")"
truncate -s 1M "$p/avocado-os-avocado-arm64-uefi-v9.img" "$p/avocado-os-arm64-uefi-v9.img" "$p/avocado-arm64-uefi-v9-rootdisk.img"
out=$(run "$d" arm64-uefi-v9 --dry-run)
rc=$?
{ [ $rc -eq 0 ] && grep -qxF "image: $p/avocado-os-avocado-arm64-uefi-v9.img" <<<"$out"; } \
  && ok "the platform-named image is preferred" || bad "platform: rc=$rc out=[$out]"

# 7. Only the platform-named image present is selected.
d=$(workdir platform-only)
p="$(deploy "$d")"
truncate -s 1M "$p/avocado-os-avocado-qemuarm64.img"
out=$(run "$d" qemuarm64 --dry-run)
rc=$?
{ [ $rc -eq 0 ] && grep -qxF "image: $p/avocado-os-avocado-qemuarm64.img" <<<"$out"; } \
  && ok "a lone platform-named image is selected" || bad "platform only: rc=$rc out=[$out]"

# 8. The machine-named image wins over the root-disk image.
d=$(workdir machine-named)
p="$(deploy "$d")"
truncate -s 1M "$p/avocado-os-qemux86-64.img" "$p/avocado-qemux86-64-rootdisk.img"
out=$(run "$d" qemux86-64 --dry-run)
rc=$?
{ [ $rc -eq 0 ] && grep -qxF "image: $p/avocado-os-qemux86-64.img" <<<"$out"; } \
  && ok "the machine-named image is preferred over the root disk" || bad "machine: rc=$rc out=[$out]"

# 9. The root-disk image is used when it is the only one.
d=$(workdir rootdisk)
p="$(deploy "$d")"
truncate -s 1M "$p/avocado-qemuarm64-rootdisk.img"
out=$(run "$d" qemuarm64 --dry-run)
rc=$?
{ [ $rc -eq 0 ] && grep -qxF "image: $p/avocado-qemuarm64-rootdisk.img" <<<"$out"; } \
  && ok "the root-disk image is the last fallback" || bad "rootdisk: rc=$rc out=[$out]"

# 10. Another machine's image does not satisfy the lookup; no image exits 1
#     naming the directory and all three names.
d=$(workdir no-image)
p="$(deploy "$d")"
truncate -s 1M "$p/avocado-os-avocado-qemux86-64.img"
out=$(run "$d" arm64-uefi-v9 --dry-run)
rc=$?
{ [ $rc -eq 1 ] && grep -qF "$p" <<<"$out" && grep -qF avocado-os-avocado-arm64-uefi-v9.img <<<"$out" \
  && grep -qF avocado-os-arm64-uefi-v9.img <<<"$out" && grep -qF avocado-arm64-uefi-v9-rootdisk.img <<<"$out" \
  && ! grep -q '^image:' <<<"$out"; } \
  && ok "no image exits 1 naming the directory and the three names" || bad "no image: rc=$rc out=[$out]"

# 11. Outside a work directory (no build/tmp) exits 1 naming build/tmp.
d="$w/bare"
mkdir -p "$d"
out=$(run "$d" qemux86-64 --dry-run)
rc=$?
{ [ $rc -eq 1 ] && grep -qF "$d/build/tmp" <<<"$out" && ! grep -q '^image:' <<<"$out"; } \
  && ok "no build/tmp exits 1 naming it" || bad "bare: rc=$rc out=[$out]"

# 12. --image replaces the lookup and needs no work directory.
c="$w/copied"
mkdir -p "$c"
truncate -s 1M "$c/disk.img"
out=$(run "$d" arm64-uefi-v9 --image "$c/disk.img" --dry-run)
rc=$?
{ [ $rc -eq 0 ] && grep -qxF "image: $c/disk.img" <<<"$out"; } \
  && ok "--image works outside a work directory" || bad "image path: rc=$rc out=[$out]"

# 13. --image wins over an image the lookup would have found.
d=$(workdir explicit-wins)
truncate -s 1M "$(deploy "$d")/avocado-os-avocado-arm64-uefi-v9.img"
out=$(run "$d" arm64-uefi-v9 --dry-run --image "$c/disk.img")
rc=$?
{ [ $rc -eq 0 ] && grep -qxF "image: $c/disk.img" <<<"$out"; } \
  && ok "--image replaces the work-directory lookup" || bad "image wins: rc=$rc out=[$out]"

# 14. A missing --image file exits 1 naming it.
out=$(run "$d" arm64-uefi-v9 --image "$c/absent.img" --dry-run)
rc=$?
{ [ $rc -eq 1 ] && grep -qF "$c/absent.img" <<<"$out" && ! grep -q '^image:' <<<"$out"; } \
  && ok "a missing --image file exits 1 naming it" || bad "absent image: rc=$rc out=[$out]"

# 15. --image with no value is a usage error, not a lookup.
out=$(run "$d" arm64-uefi-v9 --image)
rc=$?
{ [ $rc -eq 2 ] && ! grep -q '^image:' <<<"$out"; } \
  && ok "--image without a path exits 2" || bad "image no value: rc=$rc out=[$out]"

# size_of <file> -> the file size in bytes.
size_of() { stat -c %s "$1"; }
MIB=1048576

# 16. The binary comes from the machine table: x86-64 for qemux86-64, aarch64 for the rest.
for m in qemux86-64:qemu-system-x86_64 qemuarm64:qemu-system-aarch64 arm64-uefi-v9:qemu-system-aarch64; do
  d=$(workdir "bin-${m%%:*}")
  truncate -s 2048M "$(deploy "$d")/avocado-os-avocado-${m%%:*}.img"
  out=$(run "$d" "${m%%:*}" --dry-run)
  rc=$?
  { [ $rc -eq 0 ] && grep -qxF "qemu: ${m##*:}" <<<"$out"; } \
    && ok "${m%%:*} selects ${m##*:}" || bad "binary ${m%%:*}: rc=$rc out=[$out]"
done

# 17. A native sysroot binary is preferred over the host's and both it and qemu-img
#     run through the uninative loader, uninative lib dir first, then every lib dir.
d=$(workdir native)
mksysroot "$d"
img="$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
truncate -s 600M "$img"
sr="$d/build/tmp/sysroots-components/x86_64"
un="$d/build/tmp/sysroots-uninative/x86_64-linux/lib"
out=$(run "$d" qemux86-64 --dry-run)
rc=$?
want="resize: $un/ld-linux-x86-64.so.2 --library-path $un:$sr/glib-native/usr/lib:$sr/qemu-system-native/usr/lib $sr/qemu-system-native/usr/bin/qemu-img resize -f raw $img 1024M"
{ [ $rc -eq 0 ] && grep -qxF "$want" <<<"$out" && grep -qxF 'qemu: qemu-system-x86_64' <<<"$out"; } \
  && ok "native binaries run through the uninative loader" || bad "native dry: rc=$rc out=[$out] want=[$want]"

# 18. The native resize really goes through the loader.
: >"$log"
out=$(run "$d" qemux86-64)
rc=$?
{ [ $rc -eq 0 ] && [ "$(size_of "$img")" -eq $((1024 * MIB)) ] && grep -q '^loader --library-path ' "$log" \
  && grep -qxF 'qemu-img resize -f raw '"$img"' 1024M' "$log"; } \
  && ok "a native resize runs qemu-img under the loader" || bad "native run: rc=$rc size=$(size_of "$img") log=[$(cat "$log")]"

# 19. With no native sysroot the host's tools from PATH are used.
d=$(workdir host-only)
img="$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
truncate -s 600M "$img"
out=$(run "$d" qemux86-64 --dry-run)
rc=$?
{ [ $rc -eq 0 ] && grep -qxF "resize: $hs/qemu-img resize -f raw $img 1024M" <<<"$out" && ! grep -q ld-linux <<<"$out"; } \
  && ok "host tools are used when there is no native sysroot" || bad "host: rc=$rc out=[$out]"

# 20. Neither a native binary nor a host one exits 1 naming the sysroot path and PATH.
d=$(workdir neither)
truncate -s 600M "$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
out=$(cd "$d" && env PATH="$tools" RUN_QEMU_FIRMWARE_DIRS="$fwdefault" RUN_QEMU_HOST_QEMU_DATA_DIR="$w/hostdata" bash "$script" qemux86-64 --dry-run </dev/null 2>&1)
rc=$?
{ [ $rc -eq 1 ] && grep -qF "$d/build/tmp/sysroots-components/x86_64/qemu-system-native/usr/bin/qemu-system-x86_64" <<<"$out" \
  && grep -qF "PATH=$tools" <<<"$out" && ! grep -q '^resize:' <<<"$out"; } \
  && ok "no QEMU anywhere exits 1 naming the sysroot path and PATH" || bad "neither: rc=$rc out=[$out]"

# resize_case <name> <machine> <initial size> <expected MiB or none>
# Runs for real (no --dry-run): the stub qemu-img truncates the image to the
# requested size, so the resulting size proves what was asked for. The stub
# QEMU then exits 0.
resize_case() {
  local name=$1 machine=$2 start=$3 want=$4 d i out rc got
  d=$(workdir "rs-$name")
  i="$(deploy "$d")/avocado-os-avocado-$machine.img"
  truncate -s "$start" "$i"
  before=$(size_of "$i")
  : >"$log"
  out=$(run "$d" "$machine" --dry-run)
  got=$(size_of "$i")
  if [ "$want" = none ]; then
    { [ "$got" -eq "$before" ] && grep -qxF 'resize: none' <<<"$out" && [ ! -s "$log" ]; } \
      && ok "$name: dry-run reports no resize" || bad "$name dry: out=[$out]"
  else
    { [ "$got" -eq "$before" ] && grep -qF " resize -f raw $i ${want}M" <<<"$out" && [ ! -s "$log" ]; } \
      && ok "$name: dry-run reports the resize and changes nothing" || bad "$name dry: out=[$out]"
  fi
  out=$(run "$d" "$machine")
  rc=$?
  got=$(size_of "$i")
  if [ "$want" = none ]; then
    { [ $rc -eq 0 ] && [ "$got" -eq "$before" ] && ! grep -q resize "$log"; } \
      && ok "$name: image left at $start" || bad "$name: rc=$rc size=$got before=$before log=[$(cat "$log")]"
  else
    { [ $rc -eq 0 ] && [ "$got" -eq $((want * MIB)) ] && [ "$(grep -c resize "$log")" -eq 1 ]; } \
      && ok "$name: $start resized to ${want}M" || bad "$name: rc=$rc size=$got log=[$(cat "$log")]"
  fi
}

# 21. The resize rule.
resize_case virtio-600M qemux86-64 600M 1024
resize_case virtio-1024M qemux86-64 1024M none
resize_case virtio-1500M qemux86-64 1500M none
resize_case virtio-2G qemux86-64 2G none
resize_case virtio-3000M-uefi arm64-uefi-v9 3000M none
resize_case sd-600M qemuarm64 600M 1024
resize_case sd-1024M qemuarm64 1024M none
resize_case sd-1500M qemuarm64 1500M 2048
resize_case sd-2G qemuarm64 2G none
resize_case sd-3000M qemuarm64 3000M 4096

# cmdline <output> -> the text after "command: " on the one command line.
cmdline() { sed -n 's/^command: //p' <<<"$1"; }
no_display() { ! grep -qE ' -(display|vnc|curses|sdl|gtk|spice)( |$)' <<<"$1"; }

# 22. qemux86-64: two pflash drives (code read-only, variables writable), a
#     virtio disk, -cpu max, -m 1024, no display option.
d=$(workdir prof-x86)
img="$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
truncate -s 2G "$img"
out=$(run "$d" qemux86-64 --dry-run)
rc=$?
c=$(cmdline "$out")
store="${img%.img}-efivars.fd"
{ [ $rc -eq 0 ] && [ "$(grep -c '^command: ' <<<"$out")" -eq 1 ] && grep -qF "$hs/qemu-system-x86_64 " <<<"$c" \
  && grep -qF -- "-drive if=pflash,format=raw,unit=0,readonly=on,file=$fwdefault/OVMF_CODE.fd" <<<"$c" \
  && grep -qF -- "-drive if=pflash,format=raw,unit=1,file=$store" <<<"$c" \
  && grep -qF -- "-drive file=$img,if=virtio,format=raw" <<<"$c" && grep -qF -- ' -cpu max' <<<"$c" \
  && grep -qF -- ' -m 1024' <<<"$c" && grep -qF -- ' -nographic' <<<"$c" && no_display "$c"; } \
  && ok "qemux86-64 profile: pflash pair, virtio disk, -cpu max, -m 1024, no display" || bad "x86 profile: rc=$rc out=[$out]"

# 23. qemuarm64: the old runner's arguments, secure virt, flash.bin, SD card.
d=$(workdir prof-arm)
img="$(deploy "$d")/avocado-os-avocado-qemuarm64.img"
truncate -s 2G "$img"
out=$(run "$d" qemuarm64 --dry-run)
rc=$?
c=$(cmdline "$out")
{ [ $rc -eq 0 ] && grep -qF -- ' -M virt,secure=on,highmem=off,acpi=off' <<<"$c" && grep -qF -- ' -cpu cortex-a53' <<<"$c" \
  && grep -qF -- ' -m 1024' <<<"$c" && grep -qF -- " -bios $d/build/tmp/deploy/stone/flash.bin" <<<"$c" \
  && grep -qF -- ' -device sdhci-pci' <<<"$c" && grep -qF -- ' -device sd-card,drive=mmc' <<<"$c" \
  && grep -qF -- " -drive file=$img,if=none,format=raw,id=mmc" <<<"$c" && grep -qF -- ' -nographic' <<<"$c" \
  && ! grep -q pflash <<<"$c" && no_display "$c" && [ ! -e "${img%.img}-efivars.fd" ]; } \
  && ok "qemuarm64 profile: secure virt, flash.bin, SD card, no UEFI firmware, no display" || bad "arm profile: rc=$rc out=[$out]"

# 23b. flash.bin lookup: stone/flash.bin, then stone/_build/flash.bin, then the
#      RUN_QEMU_FLASH_BIN override; none -> exit 1 naming both paths, dry run or not.
flash_case() {
  local name=$1 new=$2 old=$3 d img c out rc
  d=$(workdir "flash-$name")
  img="$(deploy "$d")/avocado-os-avocado-qemuarm64.img"
  truncate -s 2G "$img"
  rm -f "$d/build/tmp/deploy/stone/flash.bin"
  [ "$new" = 1 ] && echo new >"$d/build/tmp/deploy/stone/flash.bin"
  [ "$old" = 1 ] && echo old >"$(deploy "$d")/flash.bin"
  run "$d" qemuarm64 --dry-run >"$d/flash.out"
  echo $? >"$d/flash.rc"
}
# flash_get <name> -> sets d, rc, out from the flash_case run
flash_get() {
  d=$w/flash-$1
  rc=$(<"$d/flash.rc")
  out=$(<"$d/flash.out")
}
flash_case new 1 0
flash_get new
grep -qF -- " -bios $d/build/tmp/deploy/stone/flash.bin " <<<"$out " && [ "$rc" = 0 ] \
  && ok "flash.bin only under deploy/stone is used" || bad "flash new only: rc=$rc out=[$out]"
flash_case both 1 1
flash_get both
grep -qF -- " -bios $d/build/tmp/deploy/stone/flash.bin " <<<"$out " && [ "$rc" = 0 ] \
  && ok "both flash.bin present: deploy/stone wins" || bad "flash both: rc=$rc out=[$out]"
flash_case old 0 1
flash_get old
grep -qF -- " -bios $d/build/tmp/deploy/stone/_build/flash.bin " <<<"$out " && [ "$rc" = 0 ] \
  && ok "only the old _build flash.bin is used" || bad "flash old only: rc=$rc out=[$out]"
flash_case none 0 0
flash_get none
{ [ "$rc" = 1 ] && grep -qF "$d/build/tmp/deploy/stone/flash.bin" <<<"$out" \
  && grep -qF "$d/build/tmp/deploy/stone/_build/flash.bin" <<<"$out" && ! grep -q '^command:' <<<"$out"; } \
  && ok "no flash.bin: exit 1 naming both paths" || bad "flash none: rc=$rc out=[$out]"
d=$(workdir flash-env)
truncate -s 2G "$(deploy "$d")/avocado-os-avocado-qemuarm64.img"
echo envfw >"$w/custom-flash.bin"
out=$(RUN_QEMU_FLASH_BIN=$w/custom-flash.bin run "$d" qemuarm64 --dry-run)
rc=$?
{ [ $rc -eq 0 ] && grep -qF -- " -bios $w/custom-flash.bin " <<<"$out "; } \
  && ok "RUN_QEMU_FLASH_BIN overrides the lookup" || bad "flash env: rc=$rc out=[$out]"
out=$(RUN_QEMU_FLASH_BIN=$w/nope.bin run "$d" qemuarm64 --dry-run)
rc=$?
{ [ $rc -eq 1 ] && grep -qF "$w/nope.bin" <<<"$out"; } \
  && ok "RUN_QEMU_FLASH_BIN to a missing file exits 1" || bad "flash env missing: rc=$rc out=[$out]"

# 24. arm64-uefi-v9: ACPI virt, neoverse-n2, 2 GiB, 2 CPUs, AAVMF pflash, virtio disk.
d=$(workdir prof-uefi)
img="$(deploy "$d")/avocado-os-avocado-arm64-uefi-v9.img"
truncate -s 2G "$img"
out=$(run "$d" arm64-uefi-v9 --dry-run)
rc=$?
c=$(cmdline "$out")
store="${img%.img}-efivars.fd"
{ [ $rc -eq 0 ] && grep -qF -- ' -M virt,acpi=on ' <<<"$c" && ! grep -qF -- 'acpi=off' <<<"$c" && ! grep -qF secure <<<"$c" \
  && grep -qF -- ' -cpu neoverse-n2' <<<"$c" && grep -qF -- ' -m 2048' <<<"$c" && grep -qF -- ' -smp 2' <<<"$c" \
  && grep -qF -- "-drive if=pflash,format=raw,unit=0,readonly=on,file=$fwdefault/AAVMF_CODE.fd" <<<"$c" \
  && grep -qF -- "-drive if=pflash,format=raw,unit=1,file=$store" <<<"$c" \
  && grep -qF -- "-drive file=$img,if=virtio,format=raw" <<<"$c" && grep -qF -- ' -nographic' <<<"$c" && no_display "$c"; } \
  && ok "arm64-uefi-v9 profile: ACPI virt, neoverse-n2, AAVMF pflash, virtio disk, no display" || bad "uefi profile: rc=$rc out=[$out]"

# 25. --dry-run creates no variable store, for either UEFI machine.
{ [ ! -e "$store" ] && [ ! -e "$(deploy "$w/prof-x86")/avocado-os-avocado-qemux86-64-efivars.fd" ]; } \
  && ok "--dry-run creates no variable store" || bad "dry-run created a store"

# 26. The QEMU data dir (native sysroot) beats the host directories.
d=$(workdir dd-native)
mksysroot "$d"
sh=$d/build/tmp/sysroots-components/x86_64/qemu-system-native/usr/share/qemu
mkdir -p "$sh"
echo dcode >"$sh/edk2-x86_64-code.fd"
echo dvars >"$sh/edk2-i386-vars.fd"
echo acode >"$sh/edk2-aarch64-code.fd"
echo avars >"$sh/edk2-arm-vars.fd"
truncate -s 2G "$(deploy "$d")/avocado-os-avocado-qemux86-64.img" "$(deploy "$d")/avocado-os-avocado-arm64-uefi-v9.img"
out=$(run "$d" qemux86-64 --dry-run)
rc=$?
out2=$(run "$d" arm64-uefi-v9 --dry-run)
rc2=$?
{ [ $rc -eq 0 ] && [ $rc2 -eq 0 ] && grep -qF "readonly=on,file=$sh/edk2-x86_64-code.fd" <<<"$out" && ! grep -qF "$fwdefault" <<<"$out" \
  && grep -qF "readonly=on,file=$sh/edk2-aarch64-code.fd" <<<"$out2" && ! grep -qF "$fwdefault" <<<"$out2"; } \
  && ok "the native QEMU data dir beats the host firmware directories" || bad "data dir native: rc=$rc/$rc2 out=[$out][$out2]"

# 27. The host QEMU's data dir (documented override) also beats the host directories.
d=$(workdir dd-host)
hd=$w/hostdata-full
mkdir -p "$hd"
echo dcode >"$hd/edk2-aarch64-code.fd"
echo avars >"$hd/edk2-arm-vars.fd"
truncate -s 2G "$(deploy "$d")/avocado-os-avocado-arm64-uefi-v9.img"
out=$(HOSTDATA=$hd run "$d" arm64-uefi-v9 --dry-run)
rc=$?
{ [ $rc -eq 0 ] && grep -qF "readonly=on,file=$hd/edk2-aarch64-code.fd" <<<"$out" && ! grep -qF "$fwdefault" <<<"$out"; } \
  && ok "the host QEMU data dir beats the host firmware directories" || bad "data dir host: rc=$rc out=[$out]"

# 28. Host-only firmware: first matching directory in RUN_QEMU_FIRMWARE_DIRS, 4M variant paired with its vars.
d=$(workdir host-fw)
truncate -s 2G "$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
f1=$w/fw1
f2=$w/fw2
mkdir -p "$f1" "$f2"
echo c >"$f2/OVMF_CODE_4M.fd"
echo v >"$f2/OVMF_VARS_4M.fd"
out=$(FWDIRS=$f1:$f2 run "$d" qemux86-64 --dry-run)
rc=$?
{ [ $rc -eq 0 ] && grep -qF "readonly=on,file=$f2/OVMF_CODE_4M.fd" <<<"$out"; } \
  && ok "host-only firmware is found in the second host directory (4M pair)" || bad "host fw: rc=$rc out=[$out]"

# 29. No firmware anywhere exits 1 listing every place searched.
d=$(workdir no-fw)
truncate -s 600M "$(deploy "$d")/avocado-os-avocado-arm64-uefi-v9.img"
before=$(size_of "$(deploy "$d")/avocado-os-avocado-arm64-uefi-v9.img")
empty=$w/empty
mkdir -p "$empty"
out=$(FWDIRS=$empty:$w/nowhere HOSTDATA=$w/nodata run "$d" arm64-uefi-v9 --dry-run)
rc=$?
out2=$(FWDIRS=$empty:$w/nowhere HOSTDATA=$w/nodata run "$d" arm64-uefi-v9)
rc2=$?
{ [ $rc -eq 1 ] && [ $rc2 -eq 1 ] && grep -qF "$w/nodata" <<<"$out" && grep -qF "$empty" <<<"$out" && grep -qF "$w/nowhere" <<<"$out" \
  && ! grep -q '^command:' <<<"$out" && [ "$(size_of "$(deploy "$d")/avocado-os-avocado-arm64-uefi-v9.img")" -eq "$before" ]; } \
  && ok "no firmware exits 1 listing every place searched, before any resize" || bad "no fw: rc=$rc/$rc2 out=[$out]"

# 30. A real run creates the store from the vars template once and reuses it.
d=$(workdir store)
img="$(deploy "$d")/avocado-os-avocado-arm64-uefi-v9.img"
truncate -s 2G "$img"
store="${img%.img}-efivars.fd"
: >"$log"
out=$(run "$d" arm64-uefi-v9)
rc=$?
{ [ $rc -eq 0 ] && [ -f "$store" ] && cmp -s "$store" "$fwdefault/AAVMF_VARS.fd" && grep -qF "unit=1,file=$store" "$log" \
  && ! compgen -G "$store.tmp.*" >/dev/null; } \
  && ok "the first real run creates the store from the vars template and leaves no temp copy" || bad "store first: rc=$rc out=[$out]"
echo guest-edit >>"$store"
sum=$(cksum <"$store")
: >"$log"
out=$(run "$d" arm64-uefi-v9)
rc=$?
{ [ $rc -eq 0 ] && [ "$(cksum <"$store")" = "$sum" ] && grep -qF "unit=1,file=$store" "$log"; } \
  && ok "a second run reuses the store untouched" || bad "store second: rc=$rc out=[$out]"

# 31. The QEMU exit status passes through.
fail_hs=$w/failstubs
mkdir -p "$fail_hs"
mkstubs "$fail_hs"
printf '#!/bin/sh\nexit 7\n' >"$fail_hs/qemu-system-aarch64"
out=$(cd "$d" && env PATH="$fail_hs:$PATH" RUN_QEMU_FIRMWARE_DIRS="$fwdefault" RUN_QEMU_HOST_QEMU_DATA_DIR="$w/hostdata" bash "$script" arm64-uefi-v9 </dev/null 2>&1)
rc=$?
[ $rc -eq 7 ] && ok "the QEMU exit status is the runner's" || bad "exit status: rc=$rc out=[$out]"

# 32. Native QEMU without the uninative loader exits 1 naming the loader.
d=$(workdir no-loader)
mksysroot "$d"
rm "$d/build/tmp/sysroots-uninative/x86_64-linux/lib/ld-linux-x86-64.so.2"
truncate -s 2G "$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
out=$(run "$d" qemux86-64 --dry-run)
rc=$?
{ [ $rc -eq 1 ] && grep -qF "ld-linux-x86-64.so.2" <<<"$out" && ! grep -q '^command:' <<<"$out"; } \
  && ok "a missing uninative loader exits 1 naming it" || bad "no loader: rc=$rc out=[$out]"

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
  (cd "$d" && env PATH="${TPMSTUBS-$tpmhs}:$tools" RUN_QEMU_FIRMWARE_DIRS="$fwdefault" RUN_QEMU_HOST_QEMU_DATA_DIR="$w/hostdata" \
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
(cd "$d" && exec setsid env PATH="$sleephs:$tools" RUN_QEMU_FIRMWARE_DIRS="$fwdefault" RUN_QEMU_HOST_QEMU_DATA_DIR="$w/hostdata" \
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
: >"$log"
out=$(TPMTMP=$w/tmpd trun "$w/bare-tpm" qemux86-64 --tpm --image "$w/bare-tpm/disk.img")
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
echo flash >"$longd/build/tmp/deploy/stone/flash.bin"
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
(cd "$d" && exec setsid env PATH="$sleephs:$tools" RUN_QEMU_FIRMWARE_DIRS="$fwdefault" RUN_QEMU_HOST_QEMU_DATA_DIR="$w/hostdata" \
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

# 47. A symlinked image is sized by its target: a 2G image behind a link is not shrunk.
d=$(workdir link-image)
truncate -s 2G "$w/real-link-target.img"
ln -s "$w/real-link-target.img" "$w/link.img"
: >"$log"
out=$(run "$d" qemux86-64 --image "$w/link.img" --dry-run)
rc=$?
{ [ $rc -eq 0 ] && grep -qxF 'resize: none' <<<"$out"; } \
  && ok "a symlinked image is measured at its target, so no shrink is planned" || bad "link image: rc=$rc out=[$out]"

# 48. An empty --image value is refused, not read as "no image given".
d=$(workdir empty-image)
truncate -s 2G "$(deploy "$d")/avocado-os-avocado-qemux86-64.img"
out=$(run "$d" qemux86-64 --image "" --dry-run)
rc=$?
{ [ $rc -eq 2 ] && grep -qF -- '--image' <<<"$out"; } \
  && ok "an empty --image exits 2 naming the option" || bad "empty image: rc=$rc out=[$out]"

# 49. A comma in a path is doubled for QEMU, so it cannot add drive options.
d=$(workdir comma-image)
commaimg="$w/comma-image/x,snapshot=on.img"
truncate -s 2G "$commaimg"
out=$(run "$d" qemux86-64 --image "$commaimg" --dry-run)
rc=$?
c=$(cmdline "$out")
{ [ $rc -eq 0 ] && grep -qF -- "-drive file=$w/comma-image/x,,snapshot=on.img,if=virtio,format=raw" <<<"$c" \
  && ! grep -qF -- "x,snapshot=on" <<<"$c"; } \
  && ok "a comma in the image path is doubled in the drive option" || bad "comma image: rc=$rc out=[$out]"

# No stub swtpm may outlive the suite.
stray=$(pgrep -af "$w/.*swtpm" || true)
[ -z "$stray" ] && ok "no stub swtpm survives" || bad "stray swtpm: [$stray]"

echo "pass=$pass fail=$fail"
[ $fail -eq 0 ]
