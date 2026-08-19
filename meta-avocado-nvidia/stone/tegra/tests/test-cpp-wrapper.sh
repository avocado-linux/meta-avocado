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
# This grep catches only the historical literal form, SDK_HOST_CPP="cpp": an
# assignment of a name that is neither absolute (/...) nor a variable ($...),
# with the empty initialiser SDK_HOST_CPP="" excluded by requiring a character
# other than the closing quote. It does NOT catch SDK_HOST_CPP='cpp', nor an
# assignment through a variable holding a bare name - which is the shape the
# current code uses. The runtime guard below is what covers those; the pair is
# only sound in aggregate.
if grep -qE 'SDK_HOST_CPP="[^/$"]' "$TARGET"; then
  fail "SDK_HOST_CPP is assigned a bare literal name; the generated wrapper would exec itself"
  grep -nE 'SDK_HOST_CPP="[^/$"]' "$TARGET" | sed 's/^/       /'
else
  pass "SDK_HOST_CPP is not assigned a bare literal name"
fi

# The absolute-path guard must survive, since command -v yields a bare word for
# a builtin or alias even when every assignment goes through it.
if grep -q 'is not an absolute path' "$TARGET"; then
  pass "absolute-path guard present"
else
  fail "absolute-path guard missing; a non-absolute resolution would recurse"
fi

# The wrapper body must quote the path, or an SDK unpacked below a directory
# with a space in it makes the wrapper exec its first word.
if grep -q 'exec "${SDK_HOST_CPP}"' "$TARGET"; then
  pass "wrapper body quotes the interpolated preprocessor path"
else
  fail "wrapper body interpolates SDK_HOST_CPP unquoted; a path with a space would break the exec"
fi

# --- 2. the failure mode is real: prove recursion vs absolute path -----------
tmp_bad=$(mktemp -d)
tmp_good=$(mktemp -d)
trap 'rm -rf "$tmp_bad" "$tmp_good"' EXIT

real_cpp=$(command -v cpp 2>/dev/null || true)
skipped=0
if [ -z "$real_cpp" ]; then
  echo "  skip  no host cpp available; cannot exercise the wrapper" >&2
  skipped=2
else
  # bare name, wrapper dir first on PATH -> must NOT terminate. Assert the
  # specific signal: 124 is timeout's "the command was still running", so a
  # wrapper that is merely missing or non-executable (126/127) or a cpp that
  # rejects --version fails this rather than passing it as a recursion.
  printf '#!/bin/bash\nexec cpp "$@"\n' >"$tmp_bad/cpp"
  chmod +x "$tmp_bad/cpp"
  PATH="$tmp_bad:$PATH" timeout 5 "$tmp_bad/cpp" --version >/dev/null 2>&1
  bad_rc=$?
  if [ "$bad_rc" -eq 124 ]; then
    pass "bare-name wrapper spins until timeout kills it (failure mode reproduced)"
  else
    fail "bare-name wrapper exited $bad_rc, not 124; the test no longer reproduces the recursion"
  fi

  # absolute path, same shadowed PATH -> must succeed promptly. Quoted, as the
  # generated wrapper now is.
  printf '#!/bin/bash\nexec "%s" "$@"\n' "$real_cpp" >"$tmp_good/cpp"
  chmod +x "$tmp_good/cpp"
  if PATH="$tmp_good:$PATH" timeout 5 "$tmp_good/cpp" --version >/dev/null 2>&1; then
    pass "absolute-path wrapper reaches the real preprocessor"
  else
    fail "absolute-path wrapper did not run cpp"
  fi
fi

echo
if [ "$failures" -eq 0 ]; then
  if [ "$skipped" -gt 0 ]; then
    echo "test-cpp-wrapper: PASS (source checks only; $skipped runtime checks skipped)"
  else
    echo "test-cpp-wrapper: PASS"
  fi
  exit 0
fi
echo "test-cpp-wrapper: FAIL ($failures)"
exit 1
