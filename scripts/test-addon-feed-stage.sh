#!/usr/bin/env bash
# Prove scripts/addon-feed-stage.sh stages exactly the add-on's own packages
# and refuses any that would change a base package.
#
# What is under test is the selection rule and its guard: an add-on
# multiconfig's deploy tree also holds every base package it rebuilt from the
# same sstate, and publishing one of those under the add-on, or a different
# build of a base package name, would let a device install something the base
# feed does not ship. That is not a visible failure at publish time; it shows
# up later as a device running a package nothing tested. Real RPMs, so the
# package-name lookup is exercised too.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE="$REPO_ROOT/scripts/addon-feed-stage.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

failures=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() {
  printf '  FAIL  %s\n' "$1"
  failures=$((failures + 1))
}
check() { if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (want '$3', got '$2')"; fi; }
expect() {
  local what=$1
  shift
  if "$@"; then pass "$what"; else fail "$what"; fi
}

# mkrpm <dir> <name> <version> [payload] [extra spec line]: a noarch RPM, filed under <dir>.
mkrpm() {
  local dir=$1 name=$2 version=$3 payload=${4:-$2} extra=${5:-}
  mkdir -p "$dir" "$WORK/rpmbuild"
  cat >"$WORK/rpmbuild/$name.spec" <<EOF
Name: $name
Version: $version
Release: r0.0
Summary: test
License: MIT
BuildArch: noarch
$extra
%description
$payload
%files
EOF
  rpmbuild -bb --quiet --define "_topdir $WORK/rpmbuild" --define "_rpmdir $WORK/rpmbuild/out" \
    "$WORK/rpmbuild/$name.spec" >/dev/null 2>&1
  mv "$WORK"/rpmbuild/out/noarch/"$name"-*.rpm "$dir/"
}

stage() { "$STAGE" --base "$WORK/base" --addon "$WORK/addon" --role "$1" --out "$WORK/out-$1" 2>"$WORK/err-$1"; }
count() { find "$1" -name '*.rpm' 2>/dev/null | wc -l | tr -d ' '; }

# The base feed: one target package and one SDK package.
mkrpm "$WORK/base/cortexa76" python3-zipp 3.23.0
mkrpm "$WORK/base/x86_64_avocadosdk" nativesdk-cmake 4.1.0
# The add-on rebuilt both from the same sstate: same file, same bytes.
mkdir -p "$WORK/addon/cortexa76" "$WORK/addon/x86_64_avocadosdk"
cp -p "$WORK"/base/cortexa76/*.rpm "$WORK/addon/cortexa76/"
cp -p "$WORK"/base/x86_64_avocadosdk/*.rpm "$WORK/addon/x86_64_avocadosdk/"
# ... and its own packages, for each role.
mkrpm "$WORK/addon/cortexa76" rclcpp 28.1.21
mkrpm "$WORK/addon/noarch" ros-environment 4.2.1
mkrpm "$WORK/addon/x86_64_avocadosdk" nativesdk-colcon 0.18.0
mkrpm "$WORK/addon/all_avocadosdk" ros-sdk-env 1.0

echo "add-on with only its own packages"
if stage target; then pass "target half stages"; else fail "target half stages: $(cat "$WORK/err-target")"; fi
check "target half has rclcpp and ros-environment only" "$(count "$WORK/out-target")" 2
check "base package left out" "$(find "$WORK/out-target" -name 'python3-zipp-*' | wc -l | tr -d ' ')" 0
expect "arch dir has repodata" [ -f "$WORK/out-target/cortexa76/repodata/repomd.xml" ]
if stage sdk; then pass "sdk half stages"; else fail "sdk half stages: $(cat "$WORK/err-sdk")"; fi
check "sdk half has the add-on's SDK and all_avocadosdk packages" "$(count "$WORK/out-sdk")" 2
check "sdk half has no target arch" "$(find "$WORK/out-sdk" -name 'rclcpp-*' | wc -l | tr -d ' ')" 0

echo "trailing slashes on the trees"
"$STAGE" --base "$WORK/base/" --addon "$WORK/addon/" --role target --out "$WORK/out-slash/" >/dev/null
check "same half with trailing slashes" "$(count "$WORK/out-slash/cortexa76")" 1

echo "no add-on deploy tree for a role"
"$STAGE" --base "$WORK/base" --addon "$WORK/none" --role sdk --out "$WORK/out-empty" >/dev/null
expect "empty sdk half is still created" [ -d "$WORK/out-empty" ]
check "empty sdk half has no packages" "$(count "$WORK/out-empty")" 0
if "$STAGE" --base "$WORK/base" --addon "$WORK/none" --role target --out "$WORK/out-none" 2>"$WORK/err-none"; then
  fail "a missing target half is refused"
else
  pass "a missing target half is refused"
fi
expect "missing target half says why" grep -q "was its multiconfig built" "$WORK/err-none"

echo "a rebuilt base package that differs (drift)"
mv "$WORK/addon/cortexa76/python3-zipp-3.23.0-r0.0.noarch.rpm" "$WORK/zipp.rpm"
mkrpm "$WORK/drift" python3-zipp 3.23.0 "rebuilt differently"
cp "$WORK"/drift/*.rpm "$WORK/addon/cortexa76/"
rm -rf "$WORK/out-target"
echo previous >"$WORK/out-target-marker"
mkdir -p "$WORK/out-target" && cp "$WORK/out-target-marker" "$WORK/out-target/"
if stage target; then fail "drift is refused"; else pass "drift is refused"; fi
expect "drift names the package" grep -q 'drift: cortexa76/python3-zipp' "$WORK/err-target"
expect "a refused stage leaves the previous output" [ -f "$WORK/out-target/out-target-marker" ]
mv "$WORK/zipp.rpm" "$WORK/addon/cortexa76/python3-zipp-3.23.0-r0.0.noarch.rpm"

echo "an add-on package named like a base package (shadow)"
mkrpm "$WORK/addon/cortexa76" python3-zipp 3.24.0
if stage target; then fail "shadow is refused"; else pass "shadow is refused"; fi
expect "shadow names the package" grep -q "would replace base package 'python3-zipp'" "$WORK/err-target"
rm -f "$WORK"/addon/cortexa76/python3-zipp-3.24.0-*.rpm

echo "an add-on package that obsoletes a base package (shadow)"
mkrpm "$WORK/addon/cortexa76" python3-zipp-ng 1.0 "" "Obsoletes: python3-zipp"
if stage target; then fail "obsoleting a base package is refused"; else pass "obsoleting a base package is refused"; fi
expect "obsoletes names the base package" grep -q "would replace base package 'python3-zipp'" "$WORK/err-target"

if [ $failures -gt 0 ]; then
  echo "$failures check(s) failed"
  exit 1
fi
echo "all checks passed"
