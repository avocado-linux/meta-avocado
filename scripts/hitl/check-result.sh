#!/usr/bin/env bash
# Read a recorded HITL verdict, for use as a task verify: line.
#
# Split from imx93-harness.sh because driving the board takes minutes and
# ds-verify's per-command timeout is 120 seconds. The harness runs on demand and
# records; this reads the record. Together they give a hardware task runnable
# (test-class) evidence instead of a prose "verify: manual" line, which is what
# sits below the risk evidence floor.
#
# Exits non-zero when there is no record, when the record is a FAIL, or when the
# commit it ran against is not an ancestor of HEAD - so a result cannot vouch for
# a tree it never saw.
set -euo pipefail

MODE="${1:-}"
[ -n "$MODE" ] || { printf 'usage: check-result.sh <mode>\n' >&2; exit 2; }

RESULT_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/avocado-hitl"
FILE="${RESULT_DIR}/${MODE}.result"

if [ ! -r "$FILE" ]; then
    printf 'hitl: no recorded result for %s - run imx93-harness.sh --assert-%s\n' \
        "$MODE" "${MODE//_/-}" >&2
    exit 1
fi

read -r verdict commit stamp < "$FILE"

if [ "$verdict" != PASS ]; then
    printf 'hitl: %s recorded %s at %s (commit %s)\n' "$MODE" "$verdict" "$stamp" "$commit" >&2
    exit 1
fi

if ! git merge-base --is-ancestor "$commit" HEAD 2>/dev/null; then
    printf 'hitl: %s passed at commit %s, which is not an ancestor of HEAD - re-run on this tree\n' \
        "$MODE" "$commit" >&2
    exit 1
fi

printf 'hitl: %s PASS at %s (commit %s)\n' "$MODE" "$stamp" "$commit"
