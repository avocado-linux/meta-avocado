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
# was made against a dirty or unknown working tree, when the run did not report
# which image the board was running, when it reports an image a later run has
# superseded, when the commit it ran against is not an ancestor of HEAD, or -
# with --since - when that commit is not a strict descendant of the named commit.
#
# Those guards answer five different questions and none of them substitutes for
# another. Tree-state rejects a result whose commit describes code the run did
# not use. Ancestor-of-HEAD rejects a result from a rewritten or unrelated
# history. --since rejects a result that is merely old. Without those three, a
# record made for an EARLIER change is still an ancestor of HEAD and would vouch
# for work it never saw, and a record made mid-edit names a commit that is real
# and a tree that is not.
#
# The two image guards answer the question the other three cannot ask at all.
# Every one of them reads host-side git, so all three stay green across a
# reflash: the board can be running an image built from a different tree
# entirely and nothing above notices. That is measured, not feared - seven
# records were carried across two reflashes during this work and every one kept
# validating.
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

read -r verdict commit stamp tree image <"$FILE"

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

# Everything above this point is about the TREE. Nothing above it can see the
# BOARD, and that is the gap this block closes: a record whose commit is an
# ancestor of HEAD, whose tree was clean, and whose verdict is PASS still says
# nothing about whether the board was carrying that code when it ran. Seven
# records survived two reflashes during this work and all seven kept validating.
is_digest() {
  case "$1" in
    [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) return 0 ;;
    *) return 1 ;;
  esac
}

# `none` is a real answer - the mode never reaches a Linux shell, so there was
# nothing to ask. `unknown` and an EMPTY field are not: the first means a shell
# was reached and no digest came back, the second means the record predates this
# field entirely. Both are rejected for the same reason the tree field rejects
# them, which is that failing to ask is not a clean answer. A record written
# before this check existed therefore fails loudly and is re-run rather than
# being grandfathered in on a field it does not carry.
if [ "$image" != none ] && ! is_digest "$image"; then
  printf 'hitl: %s recorded no board image identity (got %s) - the run never reported what the board was running, so this record cannot be tied to an image. Re-run it.\n' \
    "$LABEL" "${image:-<absent>}" >&2
  exit 1
fi

# The board runs one image at a time, so records naming different images cannot
# all describe it. The newest record carrying a digest defines what is on the
# board right now - records are only ever written by a run against it, so the
# most recent one is by construction the most recent observation - and any
# record disagreeing with that one was made before a reflash.
#
# Freshness is taken from the recorded STAMP, not from file mtime. The stamps
# are ISO-8601 UTC and sort lexically, and mtime is the wrong question anyway:
# copying the state directory, or a restore, rewrites mtime while the run it
# describes is unchanged.
#
# `none` records cannot participate on either side. They carry no digest to
# compare, and they are never stale for this reason alone - the mode that writes
# them never had a shell to ask.
newest_stamp=""
newest_image=""
for other in "$RESULT_DIR"/*.result; do
  [ -r "$other" ] || continue
  read -r _overdict _ocommit ostamp _otree oimage <"$other" || continue
  is_digest "$oimage" || continue
  if [ -z "$newest_stamp" ] || [[ "$ostamp" > "$newest_stamp" ]]; then
    newest_stamp="$ostamp"
    newest_image="$oimage"
  fi
done

if [ "$image" != none ] && [ -n "$newest_image" ] && [ "$image" != "$newest_image" ]; then
  printf 'hitl: %s passed against board image %s, but the most recent run on this board (%s) saw image %s - the board was reflashed after this record was made, so it describes software the board no longer carries. Re-run it.\n' \
    "$LABEL" "$image" "$newest_stamp" "$newest_image" >&2
  exit 1
fi

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

printf 'hitl: %s PASS at %s (commit %s, image %s)\n' "$LABEL" "$stamp" "$commit" "$image"
