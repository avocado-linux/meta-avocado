#!/usr/bin/env bash
#
# Every SDK hook must split AVOCADO_STONE_INCLUDE_PATHS on ':'.
#
# The CLI joins the composed include paths with ':'. A hook that splits on
# whitespace instead hands stone a single `-i "a:b"` naming a path that does
# not exist, so extension-provided files (carrier overlays, custom DTBs) stop
# shadowing anything and the build carries on without them.
#
# This lifts build_include_flags out of every hook in the repository and runs
# it against a two-path value, one path containing a space.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
failures=0
checked=0

pass() { printf '  ok   %s\n' "$1"; }
fail() {
  printf '  FAIL %s\n' "$1"
  failures=$((failures + 1))
}

echo "test-stone-include-paths: $ROOT"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

while IFS= read -r hook; do
  rel="${hook#"$ROOT"/}"
  awk '/^build_include_flags\(\) \{/{f=1} f{print} f&&/^\}$/{exit}' \
    "$hook" >"$work/fn.sh"
  checked=$((checked + 1))

  # The flags string is built for eval, so eval it the way the hooks do and
  # inspect the resulting argv.
  args=$(
    AVOCADO_STONE_INCLUDE_PATHS="/ext/a b:/ext/c" AVOCADO_SDK_PREFIX=/sdk bash -c '
      . "$1"
      eval "set -- $(build_include_flags /in)"
      printf "%s\n" "$@"
    ' _ "$work/fn.sh"
  )

  if grep -qx '/ext/a b' <<<"$args" && grep -qx '/ext/c' <<<"$args" \
    && ! grep -q ':' <<<"$args"; then
    pass "$rel"
  else
    fail "$rel: got $(tr '\n' ' ' <<<"$args")"
  fi
done < <(grep -rl --include='avocado-build-*' --include='avocado-provision-*' \
  '^build_include_flags() {' "$ROOT" | sort)

# A discovery bug would otherwise pass over an empty set.
if [ "$checked" -lt 40 ]; then
  fail "only $checked hooks found; expected at least 40"
fi

echo
if [ "$failures" -eq 0 ]; then
  echo "test-stone-include-paths: PASS ($checked hooks)"
  exit 0
fi
echo "test-stone-include-paths: FAIL ($failures of $checked)"
exit 1
