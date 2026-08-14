#!/usr/bin/env bash
#
# Regression test for the self-recursive cpp wrapper in
# stone-provision-tegraflash.sh.
#
# The provisioning script writes a wrapper named `cpp` into a mktemp dir and
# prepends that dir to PATH. If the wrapper body names the preprocessor by bare
# word, `exec cpp "$@"` re-resolves through PATH, finds the wrapper, and re-execs
# itself forever: the flash hangs in "Step 1: Signing binaries" with no output,
# no error, and one process at 100% CPU. Observed 2026-08-14 on a first flash of
# a Jetson Orin Nano; diagnosed only by walking the process tree to a wchan of
# anon_pipe_read.
#
# Test 1 is the guard against a regression in the script.
# Test 2 demonstrates the failure mode is real rather than theoretical, so a
# future reader can see why test 1 matters.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$SCRIPT_DIR/../stone-provision-tegraflash.sh"
failures=0

pass() { printf '  ok   %s\n' "$1"; }
fail() {
  printf '  FAIL %s\n' "$1"
  failures=$((failures + 1))
}

[ -f "$TARGET" ] || {
  echo "target script not found: $TARGET" >&2
  exit 1
}

echo "test-cpp-wrapper: $TARGET"

# --- 1. the script must never put a bare name in the wrapper -----------------
# Matches an assignment of a literal name that is neither absolute (/...) nor a
# variable ($...). The empty initialiser SDK_HOST_CPP="" is excluded by
# requiring a character other than the closing quote. The historical bug was
# exactly SDK_HOST_CPP="cpp".
if grep -qE 'SDK_HOST_CPP="[^/$"]' "$TARGET"; then
  fail "SDK_HOST_CPP is assigned a bare name; the generated wrapper would exec itself"
  grep -nE 'SDK_HOST_CPP="[^/$"]' "$TARGET" | sed 's/^/       /'
else
  pass "SDK_HOST_CPP is only ever assigned a resolved path"
fi

# The absolute-path guard must survive, since command -v yields a bare word for
# a builtin or alias even when every assignment goes through it.
if grep -q 'is not an absolute path' "$TARGET"; then
  pass "absolute-path guard present"
else
  fail "absolute-path guard missing; a non-absolute resolution would recurse"
fi

# --- 2. the failure mode is real: prove recursion vs absolute path -----------
tmp_bad=$(mktemp -d)
tmp_good=$(mktemp -d)
trap 'rm -rf "$tmp_bad" "$tmp_good"' EXIT

real_cpp=$(command -v cpp 2>/dev/null || true)
if [ -z "$real_cpp" ]; then
  echo "  skip  no host cpp available; cannot exercise the wrapper" >&2
else
  # bare name, wrapper dir first on PATH -> must NOT terminate
  printf '#!/bin/bash\nexec cpp "$@"\n' >"$tmp_bad/cpp"
  chmod +x "$tmp_bad/cpp"
  if PATH="$tmp_bad:$PATH" timeout 5 "$tmp_bad/cpp" --version >/dev/null 2>&1; then
    fail "bare-name wrapper terminated; the test no longer reproduces the recursion"
  else
    pass "bare-name wrapper recurses until killed (failure mode reproduced)"
  fi

  # absolute path, same shadowed PATH -> must succeed promptly
  printf '#!/bin/bash\nexec %s "$@"\n' "$real_cpp" >"$tmp_good/cpp"
  chmod +x "$tmp_good/cpp"
  if PATH="$tmp_good:$PATH" timeout 5 "$tmp_good/cpp" --version >/dev/null 2>&1; then
    pass "absolute-path wrapper reaches the real preprocessor"
  else
    fail "absolute-path wrapper did not run cpp"
  fi
fi

echo
if [ "$failures" -eq 0 ]; then
  echo "test-cpp-wrapper: PASS"
  exit 0
fi
echo "test-cpp-wrapper: FAIL ($failures)"
exit 1
