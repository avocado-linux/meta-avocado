#!/bin/sh
# Publish /var storage-security posture into the U-Boot KV store so a fleet can
# see it. Runs once per boot in the real root, after cryptsetup-var.sh has
# recorded what it did in the initramfs.
#
# The gap this closes: cryptsetup-var.sh's TPM2 enroll and TPM2 open both fail
# open on purpose, because a legitimate PCR 7 change must not lock a device out
# of its own /var. The cost of that choice is silence - a device can run on the
# Argon2id recovery slot indefinitely and look identical from outside. This puts
# the difference somewhere peridiod already reads.
#
# POSIX sh, no bash.
set -eu

POSTURE_FILE="/run/avocado-var-posture"

# Every key this script owns, so a stale value from a previous boot is never
# left behind when the corresponding fact stops being reportable.
KEY_UNLOCK="avocado_var_unlock"
KEY_TOKEN="avocado_var_tpm2_token"
KEY_ENCRYPTED="avocado_var_encrypted"

# fw_printenv/fw_setenv come from libubootenv and need a valid fw_env.config,
# which a systemd unit generates for the detected boot device earlier in boot.
# On a target with neither (or a boot medium the generator did not recognise)
# there is nothing to publish to, and that is not an error worth failing a boot
# over - posture is an observation, not a control.
if ! command -v fw_printenv >/dev/null 2>&1 || ! command -v fw_setenv >/dev/null 2>&1; then
    echo "avocado-posture: libubootenv tools absent - nothing to publish to" >&2
    exit 0
fi

# Write only when the value actually changes. The KV backend is a U-Boot
# environment block on the boot medium, and its own documentation expects
# infrequent writes; re-writing three keys on every boot would be steady flash
# wear for no new information. A change is also the interesting event - the
# first enroll, or the day a device silently drops to the recovery slot.
put_if_changed() {
    _key="$1"
    _new="$2"

    # An absent key reads as empty, which compares unequal to any real value and
    # so publishes on first boot. A failed read must not be mistaken for "absent"
    # and trigger a needless write, so treat a non-zero fw_printenv as unknown
    # and skip rather than guess.
    if ! _cur=$(fw_printenv -n "$_key" 2>/dev/null); then
        _cur=""
    fi

    [ "$_cur" = "$_new" ] && return 0

    if fw_setenv "$_key" "$_new" 2>/dev/null; then
        echo "avocado-posture: ${_key} ${_cur:-<unset>} -> ${_new}"
    else
        echo "avocado-posture: failed to publish ${_key}" >&2
    fi
    return 0
}

# Facts the initramfs observed and userspace cannot reconstruct. Absent when
# cryptsetup-var.sh did not run at all (an unencrypted build), in which case
# there is no /var posture to report and the script is a no-op.
if [ ! -r "$POSTURE_FILE" ]; then
    echo "avocado-posture: no $POSTURE_FILE - /var encryption not in this image" >&2
    exit 0
fi

VAR_UNLOCK_METHOD=unknown
VAR_TPM2_TOKEN=unknown
# shellcheck source=/dev/null
. "$POSTURE_FILE"

# The one fact worth re-checking here rather than trusting from the initrd:
# whether /var ended up mounted through the mapper. cryptsetup-var.sh opening
# the container says nothing about what fstab then mounted - that mismatch was a
# real defect on this board (AVOCADO_VAR_PART_DEV unset), where the container was
# opened in the initrd while /var mounted from the raw partition underneath it.
var_encrypted=no
if _src=$(findmnt -no SOURCE /var 2>/dev/null); then
    case "$_src" in
        /dev/mapper/*) var_encrypted=yes ;;
    esac
fi

put_if_changed "$KEY_UNLOCK" "$VAR_UNLOCK_METHOD"
put_if_changed "$KEY_TOKEN" "$VAR_TPM2_TOKEN"
put_if_changed "$KEY_ENCRYPTED" "$var_encrypted"

# Loud on the degraded case. Everything above is a value in a store someone has
# to go looking at; this is the line that shows up in journalctl -p warning on a
# device that is encrypted but no longer TPM-bound.
if [ "$var_encrypted" = yes ] && [ "$VAR_TPM2_TOKEN" = yes ] && [ "$VAR_UNLOCK_METHOD" = argon2id ]; then
    echo "avocado-posture: /var has a TPM2 keyslot but opened with the Argon2id recovery key - PCR 7 no longer matches what was sealed" >&2
fi
