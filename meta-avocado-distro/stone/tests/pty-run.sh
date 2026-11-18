#!/usr/bin/env bash
# Test helper: run a command with a real terminal on stdin, feeding it typed
# input, so a test can drive a prompt that checks `[ -t 0 ]`.
#
#   run_with_tty 'y\n' cmd args...
#
# $1 is a printf format for the keystrokes. The command's output (with the
# terminal's CRLF) goes to stdout and its exit status is returned. Needs
# script(1) from util-linux.
run_with_tty() {
  local input=$1 cmd
  shift
  printf -v cmd '%q ' "$@"
  # shellcheck disable=SC2059 # the caller supplies a printf format on purpose
  printf "$input" | script -qec "$cmd" /dev/null
}
