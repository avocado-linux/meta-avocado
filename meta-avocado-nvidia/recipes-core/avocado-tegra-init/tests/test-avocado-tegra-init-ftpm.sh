#!/usr/bin/env bash
# Host test: avocado-tegra-init runs under `set -e`, and its inline fTPM setup
# call must not take the initrd down when optee-ftpm-setup.sh refuses. The setup
# script exits 1 when the image declares no ftpm capability or the kernel has no
# TEE, and as a unit that was non-fatal; called inline it must stay so.
set -u
here=$(cd "$(dirname "$0")" && pwd); script=$here/../files/avocado-tegra-init
w=$(mktemp -d); trap 'rm -rf "$w"' EXIT
pass=0; fail=0; ok(){ echo "  ok   - $1"; pass=$((pass+1)); }; bad(){ echo "  FAIL - $1"; fail=$((fail+1)); }

# The block under test: from the FTPM_SETUP assignment to its closing fi.
block=$(awk '/^FTPM_SETUP=/{on=1} on{print} on&&/^fi$/{exit}' "$script")
if [ -n "$block" ]; then ok "found the inline fTPM setup block"; else bad "block not found in $script"; echo "$pass passed, $fail failed"; exit 1; fi

# run <stub exit status|absent> -> stdout; the block runs under sh -e as the
# initrd does, and "reached" prints only if the shell survived the call.
run() {
    local stub=$w/setup.sh
    rm -f "$stub" "$w/args"
    if [ "$1" != absent ]; then
        printf '#!/bin/sh\necho "$@" > "%s"\nexit %s\n' "$w/args" "$1" > "$stub"
        chmod +x "$stub"
    fi
    # The block's first line is the FTPM_SETUP assignment; point it at the stub.
    { printf 'FTPM_SETUP=%s\n' "$stub"; tail -n +2 <<<"$block"; } > "$w/block.sh"
    rootdiskname=mmcblk0 sh -e -c '. "$1"; echo reached' _ "$w/block.sh" 2>&1
}

out=$(run 1)
case "$out" in *reached*) ok "a refusing setup script does not abort the initrd" ;; *) bad "aborted on exit 1: $out" ;; esac
case "$out" in *"exited 1"*) ok "the refusal is logged with its exit status" ;; *) bad "no log line with the exit status: $out" ;; esac

out=$(run 0)
case "$out" in *reached*) ok "a successful setup script continues" ;; *) bad "stopped on exit 0: $out" ;; esac
args=$(cat "$w/args" 2>/dev/null)
if [ "$args" = mmcblk0 ]; then ok "the boot disk name is passed through"; else bad "args: $args"; fi
case "$out" in *"exited"*) bad "logged a refusal on success: $out" ;; *) ok "success logs no refusal" ;; esac

out=$(run absent)
case "$out" in *reached*) ok "an image without optee-ftpm-init is unaffected" ;; *) bad "absent stub: $out" ;; esac

echo "$pass passed, $fail failed"; [ $fail -eq 0 ]
