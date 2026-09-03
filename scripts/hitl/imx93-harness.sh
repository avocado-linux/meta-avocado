#!/usr/bin/env bash
# Hardware-in-the-loop assertions for avocado-imx93-frdm.
#
# Exists so that hardware verification produces machine-checkable evidence
# rather than a prose "verify: manual" line. A task whose only evidence is an
# assertion sits below the risk evidence floor, which is what blocked
# uboot-env-lockdown-imx93 from archiving despite the work being done and the
# board being driven by hand.
#
# Rig, and all three values are load-bearing:
#   - KP303 power strip at 192.168.8.202, child index 0 is the imx93 outlet.
#     Index 1 is a DIFFERENT live outlet - do not use it.
#   - tio profile imx93-net, which reaches the console through ser2net on
#     localhost:3001 rather than claiming the tty directly.
#   - The board autoboots unkeyed with a ~2s window, so any byte interrupts it.
set -euo pipefail

KASA_HOST="192.168.8.202"
KASA_INDEX="0"
TIO_PROFILE="imx93-net"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LUA="${HERE}/imx93-harness.lua"

die() {
  printf 'imx93-harness: %s\n' "$*" >&2
  exit 2
}

[ -r "$LUA" ] || die "missing $LUA"
command -v tio >/dev/null 2>&1 || die "tio not on PATH"
command -v kasa >/dev/null 2>&1 || die "kasa not on PATH"

# Seconds to hold the outlet OFF. Four is enough to reboot the board and is the
# default because every assertion mode pays it on every run.
#
# It is NOT enough to clear a USB controller that came up refusing to
# initialise ("Failed to initialize board for USB", "Port not available"). That
# state survives a short cycle and needs the board unpowered for a MINUTE or
# more; export POWER_OFF_S=90 for a run that has to recover from it.
POWER_OFF_S="${POWER_OFF_S:-4}"

# Power-cycle in the background so tio is ALREADY attached when the autoboot
# window opens. Attaching after the cycle races a 2-second window and loses.
schedule_power_cycle() {
  (
    sleep 2
    kasa --host "$KASA_HOST" --type strip off --child-index "$KASA_INDEX" >/dev/null 2>&1 || true
    sleep "$POWER_OFF_S"
    kasa --host "$KASA_HOST" --type strip on --child-index "$KASA_INDEX" >/dev/null 2>&1 || true
  ) &
}

# A full run power-cycles the board and takes minutes, which is well past
# ds-verify's 120s per-command timeout. So the run RECORDS its verdict and a
# task's verify: reads that record instead of driving the board inline. The
# record names the commit it ran against, and the reader requires that commit to
# be an ancestor of HEAD - so a result stays valid across later commits that did
# not touch the board, and a rewritten history invalidates it rather than
# silently vouching for code that never ran.
RESULT_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/avocado-hitl"

# The record is keyed on mode AND argument, not mode alone. A mode that takes an
# argument runs a DIFFERENT check per value, and keying on the mode made the two
# share one file: --assert-slot-boots a followed by --assert-slot-boots b left a
# single slot_boots.result holding only the second verdict. A verify: line
# reading it could not tell which slot it described, and a passing slot A would
# be overwritten by - or would mask, depending on order - a failing slot B. That
# is a check reporting a result for work it never did, which is the failure this
# whole record mechanism exists to prevent.
result_file() {
  local mode="$1" arg="${2:-}"
  if [ -n "$arg" ]; then
    printf '%s/%s_%s.result' "$RESULT_DIR" "$mode" "$arg"
  else
    printf '%s/%s.result' "$RESULT_DIR" "$mode"
  fi
}

record_result() {
  local mode="$1" verdict="$2" arg="${3:-}" image="${4:-unknown}" commit tree porcelain
  # -C "$HERE", not a bare git. meta-avocado is a sub-repo inside the peridio
  # workspace, which is ITSELF a git repo, so a bare `git rev-parse` records
  # whichever repo the caller's cwd happened to land in. Invoked from the
  # workspace root it stamps the record with the WORKSPACE commit, and
  # check-result.sh then validates that commit against the workspace history and
  # prints PASS - while meta-avocado's own tree may have been rebased or moved
  # since the board ran. That is exactly the "vouch for a tree it never saw"
  # case the ancestry guard exists to prevent, and it is silent. Observed: a run
  # stamped 95143a88, a workspace-root commit that does not exist here.
  commit="$(git -C "$HERE" rev-parse HEAD 2>/dev/null || echo unknown)"

  # The commit alone does not describe what ran. A dirty tree at record time
  # means the board was flashed from code that is in NO commit, while the record
  # names one - so every ancestry and freshness guard downstream evaluates a
  # tree the run never saw, and each of them passes. That is not hypothetical:
  # this harness recorded a PASS against uncommitted code during the work that
  # added these assertions, and nothing anywhere reported it.
  #
  # Untracked files count as dirty, deliberately. In a Yocto layer an untracked
  # .bbappend or .cfg fragment changes the produced image exactly as an edited
  # one does, so excluding them would leave the largest class of unrecorded
  # change looking clean. Ignored paths (tmp/, build output) do not appear in
  # --porcelain at all, so a normal build tree still records clean.
  #
  # `unknown` is a THIRD state, not a synonym for clean: it means the question
  # could not be asked. check-result.sh rejects it for the same reason it
  # rejects dirty - failing to look is not evidence that nothing was there.
  # The STATUS of `git status` is read, not just its output. Capturing only the
  # output collapsed "git could not answer" into `clean`: a corrupt .git/index,
  # a held index.lock or an unreadable tree makes `git status --porcelain` exit
  # non-zero with EMPTY stdout, and the empty-string test then fell through to
  # clean. Reproduced on a scratch repo with a corrupt index and an untracked
  # file present - stamped `clean`, and check-result.sh accepted it.
  #
  # That is the same hole this whole field was added to close, one level down:
  # failing to ask is not a clean answer, so an unanswerable query lands on
  # `unknown`, which the reader rejects.
  if ! git -C "$HERE" rev-parse --git-dir >/dev/null 2>&1; then
    tree=unknown
  elif ! porcelain=$(git -C "$HERE" status --porcelain 2>/dev/null); then
    tree=unknown
  elif [ -n "$porcelain" ]; then
    tree=dirty
  else
    tree=clean
  fi

  # The image the BOARD reported, which is the one thing here the host cannot
  # infer. Commit and tree together describe the code that was checked out;
  # neither can see a reflash, so both stay green while the board runs something
  # else entirely. See the Lua side for what the digest covers and what it does
  # not.
  mkdir -p "$RESULT_DIR"
  printf '%s %s %s %s %s\n' "$verdict" "$commit" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$tree" "$image" >"$(result_file "$mode" "$arg")"
}

# Accept only what the Lua side is defined to produce: `none` for a mode that
# never reaches a Linux shell, or exactly 16 lowercase hex characters.
#
# The width is checked, not just the character class, because a TRUNCATED digest
# is the dangerous shape. A short read - the console dropping bytes mid-line,
# which this link does under load - yields a prefix that is still all-hex, still
# compares equal to itself, and would silently define a shorter namespace in
# which unrelated images collide.
valid_image() {
  case "$1" in
    none) return 0 ;;
    [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) return 0 ;;
    *) return 1 ;;
  esac
}

# Wall-clock budget per mode, in seconds. Most modes are one power cycle and one
# boot, which 300 covers with room. keydb_immutable is not: it performs three
# full boots to a login prompt and three U-Boot prompt acquisitions, so its
# internal deadlines alone (await_login(240) x3, reach_prompt x3) exceed 300
# before any of the ~25 settle() budgets are counted.
#
# Under the old flat 300 a slow boot - the first after a reflash, or a build
# carrying the full module set - killed tio mid-run and recorded FAIL with
# rc 124, indistinguishable from a real immutability failure and invisible
# because tio runs --mute. Worse, a kill landing inside part two-a leaves the
# ADVERSARIAL store installed as the board's live ubootefi.var.
#
# This file already knew 300 was not universal: --ums-hold was deliberately
# routed around run_mode for exactly this reason. The new mode was not.
mode_timeout() {
  case "$1" in
    keydb_immutable) printf '900' ;;
    *) printf '300' ;;
  esac
}

run_mode() {
  local mode="$1" arg="${2:-}" rc=0 idfile image

  # A file rather than the console, deliberately. Scraping the identity out of
  # tio's stdout would mean piping it, which costs the live view of a run that
  # can take fifteen minutes, and makes the exit status a PIPESTATUS question
  # right where a misread means recording PASS for a failed run.
  idfile="$(mktemp)"

  schedule_power_cycle
  HARNESS_MODE="$mode" HARNESS_ARG="$arg" HARNESS_ID_FILE="$idfile" \
    timeout "$(mode_timeout "$mode")" tio --script-file "$LUA" --script-run once --mute "$TIO_PROFILE" || rc=$?

  # Read what the run wrote; do not default to anything friendlier. An empty or
  # absent file means the script never funnelled through pass()/fail() - it was
  # killed by the mode timeout, or died on an error - so it never reported what
  # the board was running. `unknown` is the honest value for that, and
  # check-result.sh rejects it rather than treating silence as agreement.
  image="$(head -n1 "$idfile" 2>/dev/null || true)"
  rm -f "$idfile"
  valid_image "$image" || image=unknown

  if [ "$rc" -eq 0 ]; then
    record_result "$mode" PASS "$arg" "$image"
  else
    record_result "$mode" FAIL "$arg" "$image"
  fi
  return "$rc"
}

# --ums-hold is NOT an assertion and deliberately does not go through run_mode.
# Two reasons, and both would be bugs if it did. It records no verdict, because
# RESULT_DIR entries are read by task verify: lines as evidence that a check ran
# - and "the card was exported" is not a check of anything. And it needs far
# longer than run_mode's 300s: the export must outlive a ~120 MB fwup write, so
# the bound here is the Lua hold's own 40 minutes plus slack, not a task timeout.
# Stop an export on the BOARD. Dropping the host end does not: U-Boot keeps
# exporting, and a power cycle taken with the gadget still live is what leaves
# the USB controller unable to initialise on the next run ("Failed to initialize
# board for USB"). So the cheap Ctrl-C is worth taking on every exit path.
#
# Recovery, when it does happen, is a LONG power-off - a minute or more with the
# outlet off, which POWER_OFF_S above exists to give it. It is not a cable
# fault: this comment used to claim it needed physical cable intervention, and
# that was wrong. The wedge cleared with the cable untouched.
#
# Note the limit honestly: this is a trap, so it runs on a normal exit, on
# Ctrl-C and on SIGTERM - but NOT on SIGKILL. `pkill -9` on this harness still
# leaves the board exporting. Use plain kill.
ums_stop() {
  HARNESS_MODE="ums_stop" HARNESS_ARG="" \
    timeout 90 tio --script-file "$LUA" --script-run once --mute "$TIO_PROFILE" \
    >/dev/null 2>&1 || true
}

run_ums_hold() {
  trap ums_stop EXIT INT TERM
  schedule_power_cycle
  HARNESS_MODE="ums_hold" HARNESS_ARG="" \
    timeout 2700 tio --script-file "$LUA" --script-run once --mute "$TIO_PROFILE"
}

usage() {
  cat >&2 <<'EOF'
usage: imx93-harness.sh <mode>

  --assert-env-lockdown        saved bootcmd is rejected, saved avocado_boot_slot
                               is honoured, and the board still boots
  --assert-slot-boots <a|b>    board boots the named slot to a login prompt
  --assert-uefi-var-persists   a UEFI variable is written, survives a reset, and
                               reads back. Requires firmware with a UEFI variable
                               store; fails with a clear message on firmware that
                               has none. Proves PERSISTENCE, not tamper-resistance.
  --assert-boot-integrity-report
                               boot, then confirm the record the on-device
                               reporter publishes carries BOTH an enforcement
                               value and a root-of-trust indicator. Fails when
                               enforcement is unavailable (efivarfs never
                               appeared, so the EFI hand-off did not take), and
                               fails when the root of trust reads authenticated
                               on this board - its AHAB lifecycle cannot be
                               closed, so that reading is a reader bug.
  --assert-signed-payload-refused
                               present a payload the enrolled keys do not vouch
                               for and confirm the firmware REFUSES it. Proves
                               enforcement rather than assuming it: a board that
                               boots correctly signed images proves only that
                               the good path works, and says nothing about
                               whether verification is actually gating. Fails
                               when the bad payload is accepted, and fails when
                               the refusal cannot be distinguished from an
                               unrelated boot failure.
  --assert-keydb-immutable     confirm the enrolled key database resists BOTH a
                               runtime write from the booted system and an
                               offline edit of the variable store. Either route
                               succeeding means the enrolled keys can be
                               replaced by whoever reaches the board, which
                               makes every other signing assertion vacuous.

  --ums-hold                   NOT an assertion. Power-cycle, stop at the U-Boot
                               prompt, print `version`, export the SD card over
                               USB mass storage and hold the console until killed
                               so the host can flash the card in place. Records no
                               verdict. Read the printed version BEFORE writing:
                               changing bootloader version and config in one flash
                               is what the runbook warns against, and ums lives in
                               the bootloader being replaced.
                               Ends the export on exit - but not under SIGKILL, so
                               stop it with plain kill, never kill -9.

  --ums-stop                   Stop an export left running on the board and return
                               it to the U-Boot prompt. Idempotent. Use after a
                               --ums-hold that was killed, or whenever `ums` fails
                               with "Failed to initialize board for USB".
EOF
  exit 2
}

case "${1:-}" in
  --assert-env-lockdown) run_mode env_lockdown ;;
  --assert-slot-boots)
    [ "${2:-}" = a ] || [ "${2:-}" = b ] || die "--assert-slot-boots needs a or b"
    run_mode slot_boots "$2"
    ;;
  --assert-uefi-var-persists) run_mode uefi_var_persists ;;
  --assert-boot-integrity-report) run_mode boot_integrity_report ;;
  --assert-signed-payload-refused) run_mode signed_payload_refused ;;
  --assert-keydb-immutable) run_mode keydb_immutable ;;
  --ums-hold) run_ums_hold ;;
  --ums-stop) ums_stop ;;
  *) usage ;;
esac
