#!/bin/sh
# Publish boot-integrity state: what the firmware says it enforced, and whether
# anything vouches for the firmware saying it.
#
# The whole point is that those are two different questions. "SecureBoot=1" is a
# value read out of a variable store that the firmware itself populates. On a
# part whose bootloader is not anchored in hardware, that firmware is exactly
# what an attacker replaces, so the value it reports about itself proves
# nothing. A fleet view showing enforcement alone would read as "this boot was
# verified" when the honest reading is "something claiming to be the firmware
# said so".
#
# So enforcement is never published on its own. Every field below is written by
# ONE printf at the end of this script, on every path, including the failure
# paths - see the emit() call. That is structural rather than careful: there is
# no branch that can emit enforcement and skip the root-of-trust indicator,
# because there is only one emission and it carries all of them.
#
# Absence is reported as `unavailable`, never as a value. A device that cannot
# answer must not be indistinguishable from one that answered no - "no efivarfs"
# and "secure boot off" are different facts and a consumer acting on them would
# act differently.
#
# POSIX sh, no bash.
set -eu

RECORD="/run/avocado-boot-integrity"

# The UEFI global variable namespace. SecureBoot lives here as a 5-byte blob:
# a 4-byte attribute header then a single byte, 1 for enabled and 0 for not.
EFIVARS="/sys/firmware/efi/efivars"
EFI_GLOBAL_GUID="8be4df61-93ca-11d2-aa0d-00e098032b8c"

# Written at build time by boot-integrity.bb when the image was assembled with a
# variable store whose trust properties are known. Absent means unknown, which
# is NOT the same as trustworthy and is never reported as such.
STORE_DESC="/etc/avocado/boot-integrity-store"

# Defaults are the safe reading, not the optimistic one. Every one of these is
# overwritten only by positive evidence, so a probe that fails, a file that is
# missing, or a path nobody anticipated all leave the record saying "we do not
# know" rather than "yes".
enforcement="unavailable"
rot_state="unavailable"
store_trust="unknown"
detail="no probe ran"

# --- enforcement: what the firmware reports about itself --------------------
if [ ! -d "$EFIVARS" ]; then
    # No efivarfs at all. Either the kernel was not entered through the EFI
    # stub, or this is a boot path with no UEFI variable store behind it.
    detail="efivarfs absent - kernel was not entered through the EFI stub"
elif ! _sb=$(od -An -N5 -tu1 "${EFIVARS}/SecureBoot-${EFI_GLOBAL_GUID}" 2>/dev/null); then
    # efivarfs is mounted but the variable is not there. Reported distinctly
    # from an absent efivarfs because the causes and the fixes differ.
    detail="efivarfs present but SecureBoot variable absent"
else
    # Byte 5 is the value; bytes 1-4 are the attribute header.
    _sb_value=$(printf '%s\n' "$_sb" | awk 'NF { print $5; exit }')
    case "${_sb_value:-}" in
        1) enforcement="enabled" ;;
        0) enforcement="disabled" ;;
        *) enforcement="unavailable"
           detail="SecureBoot variable unreadable or malformed" ;;
    esac
fi

# --- root of trust: whether anything vouches for that report ----------------
#
# Deliberately not derived from the value above, and deliberately not defaulted
# to authenticated on any path.
#
# Reporting an authenticated root of trust requires positive, Linux-visible
# evidence that the bootloader which populated the variable store was itself
# verified by something the running system cannot forge - on i.MX that means the
# AHAB lifecycle closed against burned SRK fuses. No such attestation is exposed
# to Linux on the platforms this ships to today, so there is nothing to read and
# the honest answer is `unauthenticated`.
#
# That is a statement about the ABSENCE OF EVIDENCE, not a claim the firmware is
# forged. It is the correct reading either way: a consumer must not treat this
# device's enforcement value as trustworthy, and that holds whether the firmware
# happens to be genuine or not.
#
# When a reader does become available, it belongs here, and it must set
# `rot_state=authenticated` only on a successful positive read - never on the
# absence of a negative one. On the current bench part this MUST report
# unauthenticated: its SRK_HASH fuse is burned byte-swapped, so AHAB cannot be
# closed on it at all, and an indicator reading authenticated would be a defect
# in this script rather than good news.
if [ "$enforcement" = "unavailable" ]; then
    # Nothing reported enforcement, so there is no claim to anchor. Keep this
    # `unavailable` rather than `unauthenticated`: the latter would assert we
    # checked an anchor and found it wanting, and we did not check anything.
    rot_state="unavailable"
else
    rot_state="unauthenticated"
    # Worded to hold for enforcement=disabled as well as enabled: what is
    # unanchored is the firmware's answer, whichever answer it gave.
    detail="firmware answered, but no hardware attestation of the firmware is readable from Linux"
fi

# --- store trust: whether the value could have been edited in place ---------
#
# Separate from the root of trust because they fail independently. A store can
# be tamper-resistant under firmware that is itself unverified, and a verified
# firmware can keep its variables in a file anyone can rewrite. The PoC is the
# second case, and a record that omitted it would let a value seen surviving a
# reboot read as one that resisted tampering - persistence is not resistance.
if [ -r "$STORE_DESC" ]; then
    # Sourced rather than parsed: the file is generated by our own recipe and
    # holds nothing but assignments.
    # shellcheck source=/dev/null
    . "$STORE_DESC"
    store_trust="${store_trust:-unknown}"
fi

emit() {
    # THE single emission point. Every field travels together, on every path,
    # so no consumer can receive enforcement without also receiving what it is
    # worth. Do not add a second printf to this script.
    printf 'enforcement=%s\nrot_state=%s\nstore_trust=%s\ndetail=%s\n' \
        "$enforcement" "$rot_state" "$store_trust" "$detail"
}

# /run so the record is rebuilt every boot and can never be stale, and stdout so
# the same record lands in the journal for a device nobody is mounting.
emit > "$RECORD"
emit

# Loud on the case a reader is most likely to misread: enforcement on, nothing
# vouching for it. This is the line that shows up in `journalctl -p warning`.
if [ "$enforcement" = "enabled" ] && [ "$rot_state" != "authenticated" ]; then
    echo "avocado-boot-integrity: firmware reports secure boot enabled, but its root of trust is ${rot_state} - do not read this as proof the boot was verified" >&2
fi
