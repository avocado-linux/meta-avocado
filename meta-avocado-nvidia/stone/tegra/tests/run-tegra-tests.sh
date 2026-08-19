#!/usr/bin/env bash
#
# run-tegra-tests.sh - run the tegra provisioning regression suites.
#
# Each test-*.sh next to this script is a self-contained suite over the
# provisioning scripts. They need no board, no BSP and no SDK: they lift the
# code under test out of the script and execute it. That is what makes them
# runnable in CI, and why they are wired into a workflow - the five failure
# modes they cover each cost a serial-console or process-tree debugging
# session, and a one-time manual check does not stop the sixth.
#
# Exit codes from a suite: 0 pass, 77 skipped (it could not run here - e.g.
# the privilege suite under root), anything else fail. A skip is reported and
# counted separately; it never counts as coverage.
#
# Usage: run-tegra-tests.sh
#
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

passed=0
skipped=0
failed=0
failed_names=()

for suite in "$DIR"/test-*.sh; do
  [ -f "$suite" ] || continue
  name="$(basename "$suite")"
  echo "=== $name"
  bash "$suite"
  rc=$?
  case "$rc" in
    0) passed=$((passed + 1)) ;;
    77) skipped=$((skipped + 1)) ;;
    *)
      failed=$((failed + 1))
      failed_names+=("$name (exit $rc)")
      ;;
  esac
  echo
done

echo "run-tegra-tests: $passed passed, $skipped skipped, $failed failed"
if [ "$failed" -ne 0 ]; then
  printf '  %s\n' "${failed_names[@]}"
  exit 1
fi
exit 0
