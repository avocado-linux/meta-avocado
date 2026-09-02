#!/usr/bin/env bash
# Read a recorded HITL verdict, for use as a task verify: line.
#
# Split from imx93-harness.sh because driving the board takes minutes and
# ds-verify's per-command timeout is 120 seconds. The harness runs on demand and
# records; this reads the record. Together they give a hardware task runnable
# (test-class) evidence instead of a prose "verify: manual" line, which is what
# sits below the risk evidence floor.
#
# Exits non-zero when there is no record, when the record is a FAIL, when the run
# was made against a dirty or unknown working tree, when the commit it ran against
# is not an ancestor of HEAD, or - with --since - when that commit is not a strict
# descendant of the named commit. The last three answer different questions:
# tree-state rejects a result whose commit describes code the run did not use,
# ancestor-of-HEAD rejects a result from a rewritten or unrelated history, and
# --since rejects a result that is merely old. Without all three, a record made
# for an EARLIER change is still an ancestor of HEAD and would vouch for work it
# never saw - and a record made mid-edit names a commit that is real and a tree
# that is not.
set -euo pipefail

# Every git query below is anchored HERE, to this script's own repository, not
# to the caller's cwd. meta-avocado is a sub-repo inside the peridio workspace,
# which is itself a git repo, so a bare `git` resolves to whichever of the two
# the caller happened to be standing in. Run from the workspace root, the
# ancestry and freshness guards would then be evaluated against the WORKSPACE
# history - a different set of commits entirely - and a record could be
# validated, or rejected, on the strength of a tree it has nothing to do with.
# The guard has to ask about the repo whose commits the records name.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  if [ $# -gt 0 ]; then
    printf 'check-result.sh: %s\n' "$1" >&2
  fi
  printf 'usage: check-result.sh <mode> [arg] [--since <commit-ish>]\n' >&2
  exit 2
}

MODE=""
ARG=""
SINCE=""
have_mode=0
have_arg=0

# Parsed by kind rather than by position: --since must work after the optional
# mode argument as well as before it. An unrecognized argument is an error, not
# a discard - a typo in the flag name must not silently disable the freshness
# check while the caller reads a green line.
while [ $# -gt 0 ]; do
  case "$1" in
    --since)
      # Both halves matter. The arity check catches `--since` with nothing after
      # it; the emptiness check catches `--since "$VAR"` where VAR is unset,
      # which passes arity, sets SINCE="", and then fails the `[ -n "$SINCE" ]`
      # test below - silently skipping the entire freshness block. A stale
      # record from before the work under test would then satisfy the
      # ancestor-of-HEAD test and print a green line, which is precisely the
      # record class --since was added to reject. An unset variable in a
      # verify: line must fail loudly, not disable the guard.
      [ $# -ge 2 ] || usage '--since requires a commit-ish'
      [ -n "$2" ] || usage '--since requires a NON-EMPTY commit-ish (an unset variable would otherwise disable the freshness check silently)'
      SINCE="$2"
      shift 2
      ;;
    -*)
      usage "unrecognized argument: $1"
      ;;
    *)
      # Modes that take an argument record one result PER argument, because they
      # run a different check per value. Pass the same argument here or the
      # reader is asking about a check nobody ran: `check-result.sh slot_boots`
      # names no slot, and answering it from either slot's record would vouch
      # for the wrong one.
      if [ "$have_mode" -eq 0 ]; then
        MODE="$1"
        have_mode=1
      elif [ "$have_arg" -eq 0 ]; then
        ARG="$1"
        have_arg=1
      else
        usage "unexpected argument: $1"
      fi
      shift
      ;;
  esac
done

[ -n "$MODE" ] || usage 'no mode given'

RESULT_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/avocado-hitl"
if [ -n "$ARG" ]; then
  FILE="${RESULT_DIR}/${MODE}_${ARG}.result"
  LABEL="$MODE $ARG"
else
  FILE="${RESULT_DIR}/${MODE}.result"
  LABEL="$MODE"
fi

if [ ! -r "$FILE" ]; then
  printf 'hitl: no recorded result for %s - run imx93-harness.sh --assert-%s %s\n' \
    "$LABEL" "${MODE//_/-}" "$ARG" >&2
  exit 1
fi

read -r verdict commit stamp tree <"$FILE"

if [ "$verdict" != PASS ]; then
  printf 'hitl: %s recorded %s at %s (commit %s)\n' "$LABEL" "$verdict" "$stamp" "$commit" >&2
  exit 1
fi

# The commit names a tree; this says whether the run actually used it. A record
# made while the working tree was dirty describes code that is in no commit, so
# the ancestry and freshness guards below both evaluate a tree the board never
# ran - and both pass, because the commit they check is real. Rejecting here is
# what makes the two guards below mean what they say.
#
# `clean` is the only accepted value, and the two rejected ones are distinct on
# purpose. `dirty` says the run is known to have used uncommitted code.
# Anything else - `unknown` from a harness that could not query git, or an
# EMPTY field from a record written before the harness stamped one at all -
# says the question was never answered, and an unanswered question is not a
# clean answer. A legacy record therefore fails loudly and is re-run, rather
# than being grandfathered in on the strength of a field it does not carry.
case "$tree" in
  clean) ;;
  dirty)
    printf 'hitl: %s passed at commit %s but the working tree was DIRTY - the board ran code that is in no commit, so this record vouches for a tree nobody has. Commit the work and re-run.\n' \
      "$LABEL" "$commit" >&2
    exit 1
    ;;
  *)
    printf 'hitl: %s recorded no working-tree state (got %s) - either the harness could not query git, or the record predates this check. Re-run it.\n' \
      "$LABEL" "${tree:-<absent>}" >&2
    exit 1
    ;;
esac

if ! git -C "$HERE" merge-base --is-ancestor "$commit" HEAD 2>/dev/null; then
  printf 'hitl: %s passed at commit %s, which is not an ancestor of HEAD - re-run on this tree\n' \
    "$LABEL" "$commit" >&2
  exit 1
fi

if [ -n "$SINCE" ]; then
  since_sha=$(git -C "$HERE" rev-parse --verify --quiet "${SINCE}^{commit}") || {
    printf 'hitl: --since %s does not resolve to a commit\n' "$SINCE" >&2
    exit 2
  }
  commit_sha=$(git -C "$HERE" rev-parse --verify --quiet "${commit}^{commit}") || {
    printf 'hitl: %s recorded commit %s does not resolve in this tree\n' "$LABEL" "$commit" >&2
    exit 1
  }
  # Strict: a record AT the named commit predates the work that starts there, and
  # `git merge-base --is-ancestor A A` is true, so the equality case is rejected
  # separately rather than left to the ancestor test.
  if [ "$commit_sha" = "$since_sha" ] || ! git -C "$HERE" merge-base --is-ancestor "$since_sha" "$commit_sha"; then
    printf 'hitl: %s passed at commit %s, which is not newer than %s - the record predates this work, re-run\n' \
      "$LABEL" "$commit" "$SINCE" >&2
    exit 1
  fi
fi

printf 'hitl: %s PASS at %s (commit %s)\n' "$LABEL" "$stamp" "$commit"
