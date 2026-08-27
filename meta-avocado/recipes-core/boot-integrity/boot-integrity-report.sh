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

# Mount table, so "the directory is there" and "something is mounted on it" stay
# separable. /sys/firmware/efi/efivars exists as a bare mount POINT on a machine
# that booted through EFI but never mounted efivarfs, and an empty directory
# then reads exactly like a firmware with no SecureBoot variable. Observed on
# avocado-imx93-frdm: the kernel logged "efivars: Registered efivars operations"
# and the directory was still empty, because nothing had mounted it.
MOUNTS="/proc/mounts"

# Defaults are the safe reading, not the optimistic one. Every one of these is
# overwritten only by positive evidence, so a probe that fails, a file that is
# missing, or a path nobody anticipated all leave the record saying "we do not
# know" rather than "yes".
enforcement="unavailable"
rot_state="unavailable"
store_trust="unknown"
keydb_origin="unknown"
detail="no probe ran"

# --- enforcement: what the firmware reports about itself --------------------
if [ ! -d "$EFIVARS" ]; then
  # No efivarfs at all. Either the kernel was not entered through the EFI
  # stub, or this is a boot path with no UEFI variable store behind it.
  detail="efivarfs absent - kernel was not entered through the EFI stub"
elif [ -r "$MOUNTS" ] && ! awk -v p="$EFIVARS" '$2 == p { found = 1 } END { exit !found }' "$MOUNTS"; then
  # The mount point is there and nothing is on it. Distinguished from the
  # branch below because the causes are opposite: this is a userspace mount
  # that did not happen, not firmware that reported nothing, and a consumer
  # chasing the wrong one wastes the whole investigation.
  detail="efivarfs directory present but not mounted - no variables are readable"
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
    *)
      enforcement="unavailable"
      detail="SecureBoot variable unreadable or malformed"
      ;;
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
# The reader below is the one place a future attestation gets read, so that a
# part which does expose one is a change to a single function rather than a hunt
# through assignments. On the current bench part it MUST report unauthenticated:
# its SRK_HASH fuse is burned byte-swapped, so AHAB cannot be closed on it at
# all, and an indicator reading authenticated would be a defect in this script
# rather than good news.

# Candidate sources that could attest this platform's firmware. On i.MX that is
# the AHAB lifecycle, closed against burned SRK fuses. No kernel we ship exposes
# it, so this list is expected to resolve to nothing today; it exists so the
# part that does expose it has somewhere defined to be read from.
ROT_SOURCES="/sys/devices/soc0/lifecycle /sys/devices/platform/soc/ahab/lifecycle"

# Echoes exactly one of `authenticated`, `unauthenticated`, `unavailable`.
#
# The fail direction is fixed and one-way: `authenticated` requires a source
# that was found AND read AND parsed AND matched a closed lifecycle. A command
# exiting 0 is not evidence of anything - only a value that matched is. No
# source, an unreadable source, an unparseable one, a non-zero exit, or a string
# nobody recognises all fall through to `unauthenticated`, which reports the
# absence of evidence rather than a claim the firmware is forged.
#
# `unavailable` is reserved for enforcement itself being unavailable: there is
# then no claim to anchor, and `unauthenticated` would assert we checked an
# anchor and found it wanting when we checked nothing.
read_rot_evidence() {
  if [ "$enforcement" = "unavailable" ]; then
    echo "unavailable"
    return 0
  fi

  for _rot_src in $ROT_SOURCES; do
    [ -r "$_rot_src" ] || continue
    _rot_raw=$(cat "$_rot_src" 2>/dev/null) || continue
    case "$_rot_raw" in
      "OEM closed" | oem_closed | closed)
        echo "authenticated"
        return 0
        ;;
    esac
  done

  echo "unauthenticated"
}

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
  keydb_origin="${keydb_origin:-unknown}"
fi

# --- key database provenance: where the trusted keys came from --------------
#
# The mapping is total and every build mode has an answer. An image built
# without the token installs no descriptor at all, so nothing is read and the
# answer is `unknown` - which is correct and must stay distinct from
# `firmware-resident`. An unknown provenance is not a trusted one; the same
# discipline `store_trust` follows, for the same reason.
case "$keydb_origin" in
  firmware-resident) ;;
  runtime-mutable) ;;
  # Absent, unreadable, no provenance line, or a value this script does not
  # recognise. All of them mean the same thing: nobody told us.
  *) keydb_origin="unknown" ;;
esac

# Called here, after the descriptor has been sourced, rather than beside the
# reader above. The descriptor is a build artifact of ours holding nothing but
# assignments, but sourcing it puts every name in this script within its reach,
# and `rot_state` is the one name that must only ever come from a positive read.
# Computing it last means no assignment outside read_rot_evidence can survive
# into the record.
rot_state=$(read_rot_evidence)
if [ "$rot_state" = "unauthenticated" ]; then
  # Worded to hold for enforcement=disabled as well as enabled: what is
  # unanchored is the firmware's answer, whichever answer it gave.
  detail="firmware answered, but no hardware attestation of the firmware is readable from Linux"
fi

emit() {
  # THE single emission point. Every field travels together, on every path,
  # so no consumer can receive enforcement without also receiving what it is
  # worth. Do not add a second printf to this script.
  printf 'enforcement=%s\nrot_state=%s\nstore_trust=%s\nkeydb_origin=%s\ndetail=%s\n' \
    "$enforcement" "$rot_state" "$store_trust" "$keydb_origin" "$detail"
}

# /run so the record is rebuilt every boot and can never be stale, and stdout so
# the same record lands in the journal for a device nobody is mounting.
emit >"$RECORD"
emit

# Loud on the case a reader is most likely to misread: enforcement on, nothing
# vouching for it. This is the line that shows up in `journalctl -p warning`.
if [ "$enforcement" = "enabled" ] && [ "$rot_state" != "authenticated" ]; then
  echo "avocado-boot-integrity: firmware reports secure boot enabled, but its root of trust is ${rot_state} - do not read this as proof the boot was verified" >&2
fi
