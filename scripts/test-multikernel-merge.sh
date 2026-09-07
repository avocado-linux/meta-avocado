#!/usr/bin/env bash
# Prove do_multikernel_merge copies an alt multiconfig's kernel RPMs into the
# shared deploy tree and NOTHING else.
#
# The shell body is extracted from the bbclass and run unmodified against a
# fabricated TOPDIR, with bbnote/bbwarn stubbed. What is under test is the
# selection rule, which is the whole point of the function: the set comes from
# the alt mc's own package_write_rpm sstate manifest, so a shared MACHINE_ARCH
# NEVRA the default mc also owns must never be copied even though it sits in
# the same alt deploy directory. Getting that wrong is not a visible failure --
# it corrupts the shared deploy area and only surfaces later, as bitbake's
# "trying to install files into a shared area when those files already exist"
# on an unrelated recipe.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BBCLASS="$REPO_ROOT/meta-avocado-distro/classes/avocado-multikernel.bbclass"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

failures=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; failures=$((failures + 1)); }
check() { if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (want '$3', got '$2')"; fi; }

TOPDIR="$WORK/build"
DEPLOY_DIR="$TOPDIR/tmp/deploy"
ALT="$TOPDIR/tmp-testmc"
ARCH=avocado_testmach
AVOCADO_MULTIKERNEL_MC_RECIPES="testmc:linux-test"

mkdir -p "$ALT/deploy/rpm/$ARCH" "$ALT/sstate-control" "$ALT/deploy/pulp-uploads" \
         "$DEPLOY_DIR/rpm/$ARCH"

# The alt mc's kernel recipe emitted these three.
for f in kernel-9.9.9-rt-1-9.9.9+rt-r0.0.$ARCH.rpm \
         kernel-module-foo-9.9.9-rt-1-9.9.9+rt-r0.0.$ARCH.rpm \
         kernel-dbg-9.9.9+rt-r0.0.$ARCH.rpm; do
    echo alt > "$ALT/deploy/rpm/$ARCH/$f"
done
# ... and this one is a shared build dep the default mc owns under the SAME
# NEVRA. It is in the alt deploy dir but not in the kernel recipe's manifest.
echo alt > "$ALT/deploy/rpm/$ARCH/base-files-3.0.14-r0.0.$ARCH.rpm"
echo default > "$DEPLOY_DIR/rpm/$ARCH/base-files-3.0.14-r0.0.$ARCH.rpm"
# A destination that already exists must not be overwritten.
echo default > "$DEPLOY_DIR/rpm/$ARCH/kernel-dbg-9.9.9+rt-r0.0.$ARCH.rpm"

{
    echo "$ALT/deploy/rpm/$ARCH/"
    echo "$ALT/deploy/rpm/$ARCH/kernel-9.9.9-rt-1-9.9.9+rt-r0.0.$ARCH.rpm"
    echo "$ALT/deploy/rpm/$ARCH/kernel-module-foo-9.9.9-rt-1-9.9.9+rt-r0.0.$ARCH.rpm"
    echo "$ALT/deploy/rpm/$ARCH/kernel-dbg-9.9.9+rt-r0.0.$ARCH.rpm"
    echo "$ALT/deploy/rpm/$ARCH/vanished-9.9.9.$ARCH.rpm"
} > "$ALT/sstate-control/manifest-$ARCH-linux-test.package_write_rpm"

echo manifest > "$ALT/deploy/pulp-uploads/linux-test.json"

bbnote() { :; }
bbwarn() { printf 'bbwarn: %s\n' "$*" >&2; }
eval "$(sed -n '/^do_multikernel_merge() {/,/^}/p' "$BBCLASS")"
do_multikernel_merge

d="$DEPLOY_DIR/rpm/$ARCH"
check "alt kernel rpm merged" \
      "$(cat "$d/kernel-9.9.9-rt-1-9.9.9+rt-r0.0.$ARCH.rpm" 2>/dev/null)" alt
check "alt kernel module rpm merged" \
      "$(cat "$d/kernel-module-foo-9.9.9-rt-1-9.9.9+rt-r0.0.$ARCH.rpm" 2>/dev/null)" alt
check "shared NEVRA not in the manifest is left alone" \
      "$(cat "$d/base-files-3.0.14-r0.0.$ARCH.rpm")" default
check "existing destination not overwritten" \
      "$(cat "$d/kernel-dbg-9.9.9+rt-r0.0.$ARCH.rpm")" default
check "manifest directory entry ignored" \
      "$([ -e "$d/" ] && echo dir)" dir
check "manifest entry with no file on disk ignored" \
      "$([ -e "$d/vanished-9.9.9.$ARCH.rpm" ] && echo present || echo absent)" absent
check "pulp-uploads merged additively" \
      "$(cat "$DEPLOY_DIR/pulp-uploads/./linux-test.json" 2>/dev/null)" manifest

# A recipe with no manifest must warn and skip, not abort the build.
AVOCADO_MULTIKERNEL_MC_RECIPES="testmc:linux-absent"
if do_multikernel_merge 2>/dev/null; then
    pass "missing manifest warns and continues"
else
    fail "missing manifest aborted the task"
fi

if [ "$failures" -ne 0 ]; then
    printf '\n%d check(s) failed\n' "$failures"
    exit 1
fi
printf '\nall checks passed\n'
