#!/usr/bin/env bash
# Host test for run-qemu: machine naming, the TPM restriction, the image lookup
# under build/tmp/deploy/stone/_build, the explicit --image path and the resize
# rule. Every case runs in its own temp work directory through --dry-run, so no
# QEMU starts. Run it by hand after any change to the runner.
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
# shellcheck disable=SC2329 # kept for the launch cases that arrive with the real launch
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
  echo "$d"
}
deploy() { echo "$1/build/tmp/deploy/stone/_build"; }

# run <dir> <args...> -> runs the runner from <dir>, stdout and stderr merged.
run() {
  local d=$1
  shift
  (cd "$d" && env PATH="$hs:$PATH" bash "$script" "$@" </dev/null 2>&1)
}

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
out=$(run "$d" qemuarm64 --image "$c/disk.img" --dry-run)
rc=$?
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
  local name=$1 machine=$2 start=$3 want=$4 d i out rc before got
  d=$(workdir "rs-$name")
  i="$(deploy "$d")/avocado-os-avocado-$machine.img"
  truncate -s "$start" "$i"
  before=$(size_of "$i")
  : >"$log"
  out=$(run "$d" "$machine" --dry-run)
  rc=$?
  got=$(size_of "$i")
  if [ "$want" = none ]; then
    { [ $rc -eq 0 ] && [ "$got" -eq "$before" ] && grep -qxF 'resize: none' <<<"$out" && [ ! -s "$log" ]; } \
      && ok "$name: no resize" || bad "$name: rc=$rc out=[$out]"
  else
    { [ $rc -eq 0 ] && [ "$got" -eq "$before" ] && grep -qxF "resize: ${want}M" <<<"$out" && [ ! -s "$log" ]; } \
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
{ [ $rc -eq 0 ] && grep -qxF 'resize: 2048M' <<<"$out"; } \
  && ok "a symlinked 1500M image grows to 2048M" || bad "symlink: rc=$rc out=[$out]"

echo "passed: $pass  failed: $fail"
[ "$fail" -eq 0 ]
