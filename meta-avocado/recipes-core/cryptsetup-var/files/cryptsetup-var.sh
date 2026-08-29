#!/bin/sh
# Unlock or first-boot-format the /var LUKS2 container.
# Called from cryptsetup-var.service in the initramfs.
#
# Usage: cryptsetup-var.sh <block-device>
#   e.g. cryptsetup-var.sh /dev/mmcblk1p8
#
# The script uses var-key.sh (in the same directory) to derive the key.
# Exit non-zero on any failure so the unit fails rather than silently
# mounting a plaintext /var.
#
# Provisioning is idempotent and resumable: each step is gated on observable
# on-disk state (LUKS header, inner filesystem, TPM2 token), so a first boot
# interrupted between steps (e.g. a power cut during field provisioning) heals
# itself on the next boot instead of wedging /var into emergency mode forever.
#
# POSIX sh (not bash) so the initramfs needs no bash dependency.
set -eu

VAR_DEV="${1:-}"
MAP_NAME="var"
MAPPER="/dev/mapper/${MAP_NAME}"

[ -z "$VAR_DEV" ] && { echo "Usage: $0 <block-device>" >&2; exit 1; }
[ -b "$VAR_DEV" ] || { echo "Not a block device: $VAR_DEV" >&2; exit 1; }

# Fail-closed pre-flight: refuse before any luksFormat/luksOpen attempt if
# either (a) this device's base image never declared encrypted-var, or (b)
# the kernel cannot actually deliver dm-crypt. These two refusal paths must
# stay distinguishable per design.md A6 - a declaration problem and a kernel
# problem need different fixes, so collapsing them into one message would
# hide which side to fix.
CAPABILITIES_FILE="/etc/avocado-security-capabilities"
REQUIRED_CAPABILITY="encrypted-var"

check_capability_declared() {
    if [ ! -f "$CAPABILITIES_FILE" ]; then
        echo "cryptsetup-var: $CAPABILITIES_FILE is absent - this device's base image never declared $REQUIRED_CAPABILITY" >&2
        exit 1
    fi
    declared="$(cat "$CAPABILITIES_FILE")"
    for token in $declared; do
        [ "$token" = "$REQUIRED_CAPABILITY" ] && return 0
    done
    echo "cryptsetup-var: $REQUIRED_CAPABILITY is missing from this device's AVOCADO_SECURITY_CAPABILITIES declaration (declares: ${declared:-<empty>})" >&2
    exit 1
}

check_dmcrypt_available() {
    [ -e /sys/module/dm_crypt ] && return 0
    if command -v modprobe >/dev/null 2>&1 && modprobe dm-crypt 2>/dev/null; then
        return 0
    fi
    echo "cryptsetup-var: this device's kernel cannot deliver dm-crypt - /var encryption is unavailable" >&2
    exit 1
}

check_capability_declared
check_dmcrypt_available

SCRIPT_DIR="$(dirname "$0")"
KEY_SCRIPT="${SCRIPT_DIR}/var-key.sh"

# Derive the key (never hardcoded; sourced from var-key.sh).
# The key is written to a temp file to avoid exposure in /proc. Use /run, not
# /tmp: systemd mounts a fresh tmpfs over /tmp partway through early boot, which
# would shadow a key file created here before that mount and make cryptsetup's
# --key-file fail with "Failed to open key file". /run is a stable early tmpfs
# (RAM-only, never swapped or remounted) - the right place for transient secrets.
KEY_FILE=$(mktemp -p /run)
trap 'rm -f "$KEY_FILE"' EXIT
"$KEY_SCRIPT" > "$KEY_FILE"

# Return 0 if the LUKS header already carries a systemd-tpm2 token. The initrd
# has no grep, and gawk mishandles raw binary under some locales, so match the
# token type via awk over luksDump.
has_tpm2_token() {
    cryptsetup luksDump "$VAR_DEV" 2>/dev/null | awk '/systemd-tpm2/{f=1} END{exit !f}'
}

# Optional hardware key backend: var-hwkey.sh next to this script, installed by
# a vendor layer for machines with a key-wrapping engine but no TPM (CAAM on
# i.MX 8M). It supplies the passphrase of a second keyslot; the Argon2id keyslot
# stays as the recovery path exactly as with the TPM2 token. Contract:
#   var-hwkey.sh probe               exit 0 when the engine is usable right now
#   var-hwkey.sh name                backend name for posture (e.g. "caam")
#   var-hwkey.sh new    <blob-file>  make a device-bound blob, write it as one text line
#   var-hwkey.sh derive <blob-file>  print the passphrase that blob yields here
# The blob is public: it yields the passphrase only on the SoC that made it. It
# lives in the LUKS2 header as an "avocado-hwkey" token, so it travels with the
# container and needs no extra partition or writable filesystem.
HWKEY_SCRIPT="${SCRIPT_DIR}/var-hwkey.sh"
HWKEY_TOKEN_TYPE="avocado-hwkey"

# Every open links the volume key into root's user keyring under this name.
# Nothing in the running system can reproduce a keyslot passphrase (the
# hardware backends and the derived key live only in this initramfs), so this
# is how `avocadoctl var-key` authorises adding or removing the operator's
# recovery keyslot later: luksAddKey --volume-key-keyring. A `user` key, not
# `logon`, because cryptsetup has to read it back; root on the device could
# already reach the volume key through the running dm-crypt mapping.
VK_LINK="--link-vk-to-keyring @u::%user:cryptsetup:var"
RECOVERY_TOKEN_TYPE="avocado-recovery"

# avocado.yaml runtimes.<r>.var.hardware, written by avocado-cli next to the
# var-encrypt marker only when it is not the default "auto": caam|tpm2 = that
# engine must hold a keyslot, refuse to boot on the derived key if it cannot;
# none = never enrol a hardware keyslot (the operator's recovery key is the
# second slot; avocado-cli refuses "none" without one).
VAR_HARDWARE=$(cat /etc/avocado/var-hardware 2>/dev/null || echo auto)

# Fail closed when an explicitly required engine is not usable. Runs before the
# container is touched so an unmet requirement never opens /var on the
# derived key; OnFailure= takes the boot to emergency.
check_required_hardware() {
    case "$VAR_HARDWARE" in
        caam)
            if ! hwkey_available; then
                echo "cryptsetup-var: var.hardware=caam but the CAAM key backend is not usable on this device - refusing to fall back to the derived key" >&2
                exit 1
            fi ;;
        tpm2)
            i=0
            while [ ! -e /dev/tpm0 ] && [ "$i" -lt 15 ]; do i=$((i + 1)); sleep 1; done
            if [ ! -e /dev/tpm0 ]; then
                echo "cryptsetup-var: var.hardware=tpm2 but no TPM device appeared - refusing to fall back to the derived key" >&2
                exit 1
            fi ;;
        auto|none) ;;
        *)
            echo "cryptsetup-var: unknown var.hardware '$VAR_HARDWARE' - refusing to guess" >&2
            exit 1 ;;
    esac
}

has_recovery_token() {
    cryptsetup luksDump "$VAR_DEV" 2>/dev/null | awk -v t="$RECOVERY_TOKEN_TYPE" '
        /^Tokens:/ {s=1; next}
        /^[A-Za-z]/ {s=0}
        s && $2==t {f=1}
        END {exit !f}'
}

# Keyslots no token references: the Argon2id slot derived from the SoC UID (or
# the provisioned secret). With an operator recovery slot enrolled it is the
# one remaining key anyone who can read the UID could derive, so retire it.
untokened_keyslots() {
    cryptsetup luksDump "$VAR_DEV" 2>/dev/null | awk '
        /^Keyslots:/ {s=1; next}
        /^Tokens:/ {s=2; next}
        /^[A-Za-z]/ {s=0}
        s==1 && /^  [0-9]+: / {sub(":","",$1); k[$1]=1}
        s==2 && /Keyslot:/ {delete k[$2]}
        END {for (i in k) print i}'
}

hwkey_available() {
    [ -x "$HWKEY_SCRIPT" ] && "$HWKEY_SCRIPT" probe >/dev/null 2>&1
}

# Id of the avocado-hwkey token in the header, empty when there is none.
hwkey_token_id() {
    cryptsetup luksDump "$VAR_DEV" 2>/dev/null | awk -v t="$HWKEY_TOKEN_TYPE" '
        /^Tokens:/ {s=1; next}
        /^[A-Za-z]/ {s=0}
        s && $2==t {sub(":","",$1); print $1; exit}'
}

has_hwkey_token() {
    [ -n "$(hwkey_token_id)" ]
}

# First unused keyslot number, for luksAddKey --new-key-slot.
free_keyslot() {
    cryptsetup luksDump "$VAR_DEV" 2>/dev/null | awk '
        /^Keyslots:/ {s=1; next}
        /^[A-Za-z]/ {s=0}
        s && /^  [0-9]+: / {sub(":","",$1); u[$1]=1}
        END {for (i = 0; i < 32; i++) if (!u[i]) {print i; exit}}'
}

# Write the passphrase the token blob yields on this device to $1. Non-zero when
# there is no token, the engine refuses the blob, or the backend printed nothing.
hwkey_passphrase_to() {
    _id=$(hwkey_token_id)
    [ -n "$_id" ] || return 1
    _blob=$(mktemp -p /run)
    cryptsetup token export --token-id "$_id" "$VAR_DEV" 2>/dev/null \
        | sed -n 's/.*"blob" *: *"\([^"]*\)".*/\1/p' > "$_blob"
    _rc=1
    if [ -s "$_blob" ] && "$HWKEY_SCRIPT" derive "$_blob" > "$1" 2>/dev/null && [ -s "$1" ]; then
        _rc=0
    fi
    rm -f "$_blob"
    return $_rc
}

# Some firmware TPMs keep no NV state across boots. Measured on Jetson Orin
# (NVIDIA OP-TEE fTPM, ms-tpm-20-ref): the seeds are stable - a credential
# sealed on one boot unseals on the next, so a TPM2 keyslot is sound - but the
# dictionary-attack state resets every boot to inLockout=1 with maxTries=0,
# and every object load then fails with TPM_RC_LOCKOUT (0x921) until a
# DictionaryAttackLockReset. lockoutAuth cannot be persisted either, so the
# reset is free; DA protection is therefore nil on such parts, which is
# acceptable here because the sealed keyslot carries a PCR policy and no auth
# value. Best-effort and silent where tpm2-tools are absent or the TPM is not
# in lockout.
ensure_tpm2_unlocked() {
    [ -e /dev/tpm0 ] || return 0
    command -v tpm2_getcap >/dev/null 2>&1 || return 0
    if tpm2_getcap properties-variable 2>/dev/null | awk '/inLockout:/{f=($2==1)} END{exit !f}'; then
        echo "cryptsetup-var: TPM is in dictionary-attack lockout at boot - resetting"
        tpm2_dictionarylockout --clear-lockout 2>/dev/null \
            && tpm2_dictionarylockout --setup-parameters --max-tries=32 \
                   --recovery-time=600 --lockout-recovery-time=86400 2>/dev/null \
            || echo "cryptsetup-var: TPM lockout reset failed - TPM2 unlock will fall back to the recovery key" >&2
    fi
}

# Which keyslot actually opened /var this boot. Recorded because it is the one
# posture fact that cannot be recovered afterwards: a luksDump later shows that
# a TPM2 token EXISTS, not that it was the thing that worked. ensure_tpm2_enroll
# below deliberately fails open, so a device whose PCR 7 moved keeps booting on
# the Argon2id recovery slot indefinitely and nothing upstream notices.
VAR_UNLOCK_METHOD="unknown"

# Published to /run, not to the U-Boot KV store, because neither fw_setenv nor
# its fw_env.config exists in this initramfs (see the recipe's RDEPENDS note,
# and the fw_env.config generator that runs in the real root). /run is the same
# early tmpfs the key file above already depends on, and systemd carries it
# across the switch-root, so a userspace unit can publish it from there.
POSTURE_FILE="/run/avocado-var-posture"

# Best-effort by construction: posture reporting must never be the reason /var
# fails to open, so every write is guarded and the function always succeeds.
write_posture() {
    _tpm2_token=no
    if has_tpm2_token; then
        _tpm2_token=yes
    fi

    _tpm_dev=no
    if [ -e /dev/tpm0 ]; then
        _tpm_dev=yes
    fi

    _hwkey_token=no
    _hwkey_backend=none
    if has_hwkey_token; then
        _hwkey_token=yes
        _hwkey_backend=$("$HWKEY_SCRIPT" name 2>/dev/null || echo unknown)
    fi

    _recovery=soc-uid
    if has_recovery_token; then
        _recovery=key
    fi

    {
        echo "VAR_HARDWARE=${VAR_HARDWARE}"
        echo "VAR_RECOVERY=${_recovery}"
        echo "VAR_UNLOCK_METHOD=${VAR_UNLOCK_METHOD}"
        echo "VAR_TPM2_TOKEN=${_tpm2_token}"
        echo "VAR_TPM_DEVICE=${_tpm_dev}"
        echo "VAR_HWKEY_TOKEN=${_hwkey_token}"
        echo "VAR_HWKEY_BACKEND=${_hwkey_backend}"
    } > "$POSTURE_FILE" 2>/dev/null || true
}

# Open the container as /dev/mapper/var: the TPM2-sealed keyslot first (PCR 7),
# the Argon2id key file as fallback. The Argon2id keyslot (slot 0) is ALWAYS
# retained as the recovery path - it is never retired. A legitimate PCR 7 change
# (a routine dbx/Secure Boot policy update, key rotation) makes the TPM2 unseal
# fail; the recovery key then keeps /var reachable instead of locking it out
# permanently.
open_var() {
    echo "cryptsetup-var: opening LUKS2 container on $VAR_DEV"
    if has_hwkey_token; then
        _hwpass=$(mktemp -p /run)
        if hwkey_available && hwkey_passphrase_to "$_hwpass" \
                && cryptsetup luksOpen $VK_LINK --key-file "$_hwpass" "$VAR_DEV" "$MAP_NAME" 2>/dev/null; then
            rm -f "$_hwpass"
            echo "cryptsetup-var: opened via hardware key ($("$HWKEY_SCRIPT" name))"
            VAR_UNLOCK_METHOD="hwkey"
            return 0
        fi
        rm -f "$_hwpass"
        echo "cryptsetup-var: hardware key unavailable - trying the other keyslots" >&2
    fi
    if has_tpm2_token; then
        # A token exists, so a TPM is expected. On a fast reboot we can reach the
        # open before udev has created /dev/tpm0 (seen ~9s in) and wrongly fall
        # back to Argon2id. Wait briefly for the device before deciding.
        i=0
        while [ ! -e /dev/tpm0 ] && [ "$i" -lt 15 ]; do i=$((i + 1)); sleep 1; done

        # The token open needs the libcryptsetup TPM2 plugin, not the
        # systemd-cryptenroll binary - so probe capability by just attempting it
        # and letting it fall through to the Argon2id recovery key on failure.
        if [ -e /dev/tpm0 ] && cryptsetup open $VK_LINK --token-only "$VAR_DEV" "$MAP_NAME" 2>/dev/null; then
            echo "cryptsetup-var: opened via TPM2 token"
            VAR_UNLOCK_METHOD="tpm2"
            return 0
        fi
        echo "cryptsetup-var: TPM2 unseal unavailable - opening with the Argon2id recovery key" >&2
    fi

    if ! cryptsetup luksOpen $VK_LINK --key-file "$KEY_FILE" "$VAR_DEV" "$MAP_NAME" 2>/dev/null; then
        echo "cryptsetup-var: Argon2id open failed on $VAR_DEV" >&2
        exit 1
    fi
    VAR_UNLOCK_METHOD="argon2id"
}

# Ensure a filesystem exists inside the opened container (the in-place path
# keeps the flashed one; this covers the blank-partition path). This is the resume
# point for a first boot interrupted after luksFormat but before mkfs: the open
# path would otherwise leave /dev/mapper/var filesystem-less, which udev flags
# SYSTEMD_READY=0 (an empty CRYPT-* device), so dev-mapper-var.device never
# activates and var.mount times out into emergency mode - permanently, because
# the reboot path never re-formats. Probe with blkid so ANY existing filesystem
# is preserved (not only btrfs), and create the btrfs without -f so an
# unexpected foreign signature fails loudly rather than being clobbered. mkfs's
# close-after-write uevent flips SYSTEMD_READY to 1, the path a clean first boot
# relies on.
ensure_fs() {
    if blkid -p "$MAPPER" >/dev/null 2>&1; then
        return 0
    fi
    command -v mkfs.btrfs >/dev/null 2>&1 || {
        echo "cryptsetup-var: mkfs.btrfs missing; cannot create the /var filesystem" >&2
        exit 1
    }
    echo "cryptsetup-var: no filesystem on $MAPPER - creating BTRFS (first boot or resumed provisioning)"
    mkfs.btrfs "$MAPPER"
}

# Ensure a hardware-key keyslot + token exist when a backend is installed and
# its engine answers. Same posture as the TPM2 enroll: idempotent, best-effort,
# runs every boot so a device whose engine came up late still gets enrolled, and
# a failure leaves /var on the Argon2id keyslot rather than failing the unit.
# The passphrase is high-entropy engine output, so the keyslot uses a cheap
# PBKDF2 like systemd-cryptenroll does for TPM2 slots; the Argon2id cost stays
# on the recovery slot where the input is a derived secret.
ensure_hwkey_enroll() {
    [ "$VAR_HARDWARE" != none ] || return 0
    [ -x "$HWKEY_SCRIPT" ] || return 0
    has_hwkey_token && return 0
    if ! hwkey_available; then
        echo "cryptsetup-var: hardware key engine not usable - retaining Argon2id keyslot" >&2
        return 0
    fi
    _blob=$(mktemp -p /run)
    _pass=$(mktemp -p /run)
    _name=$("$HWKEY_SCRIPT" name 2>/dev/null || echo unknown)
    echo "cryptsetup-var: enrolling hardware keyslot ($_name)"
    if "$HWKEY_SCRIPT" new "$_blob" && "$HWKEY_SCRIPT" derive "$_blob" > "$_pass" && [ -s "$_pass" ]; then
        _slot=$(free_keyslot)
        if cryptsetup luksAddKey --key-file "$KEY_FILE" --new-keyfile "$_pass" \
                --new-key-slot "$_slot" --pbkdf pbkdf2 --pbkdf-force-iterations 1000 \
                --batch-mode "$VAR_DEV"; then
            printf '{"type":"%s","keyslots":["%s"],"backend":"%s","blob":"%s"}\n' \
                "$HWKEY_TOKEN_TYPE" "$_slot" "$_name" "$(tr -d '[:space:]' < "$_blob")" > "$_blob.json"
            if cryptsetup token import --json-file "$_blob.json" "$VAR_DEV"; then
                echo "cryptsetup-var: hardware keyslot $_slot enrolled ($_name)"
            else
                echo "cryptsetup-var: token import failed - removing keyslot $_slot" >&2
                cryptsetup luksKillSlot --key-file "$KEY_FILE" --batch-mode "$VAR_DEV" "$_slot" 2>/dev/null || true
            fi
        else
            echo "cryptsetup-var: hardware keyslot add failed - retaining Argon2id keyslot" >&2
        fi
    else
        echo "cryptsetup-var: hardware key backend could not produce a blob - retaining Argon2id keyslot" >&2
    fi
    rm -f "$_blob" "$_blob.json" "$_pass"
    return 0
}

# Once the operator has enrolled a recovery keyslot (avocadoctl var-key, token
# avocado-recovery), the Argon2id keyslot derived from the SoC UID stops being
# a recovery path and becomes the one key a UID reader could derive: retire it.
# Only when this boot did not depend on it - if the hardware slot failed and
# the derived key is what opened /var, keep it and let posture shout.
retire_derived_keyslot() {
    [ "$VAR_UNLOCK_METHOD" != argon2id ] || return 0
    has_recovery_token || return 0
    for _slot in $(untokened_keyslots); do
        echo "cryptsetup-var: recovery keyslot present - retiring derived keyslot $_slot"
        cryptsetup luksKillSlot --batch-mode "$VAR_DEV" "$_slot" \
            || echo "cryptsetup-var: could not retire keyslot $_slot" >&2
    done
    return 0
}

# Ensure a TPM2 keyslot sealed to PCR 7 exists, keeping the Argon2id keyslot
# (slot 0) as the recovery path. Idempotent and best-effort: skips when a token
# already exists, when no TPM is present, or when systemd-cryptenroll is absent.
# A failed enroll (e.g. firmware without measured boot) leaves the volume
# encrypted under Argon2id rather than failing the unit. Running on every boot
# also enrolls a device whose first boot happened before /dev/tpm0 existed.
ensure_tpm2_enroll() {
    [ "$VAR_HARDWARE" != none ] || return 0
    has_tpm2_token && return 0
    [ -e /dev/tpm0 ] || return 0
    command -v systemd-cryptenroll >/dev/null 2>&1 || return 0

    echo "cryptsetup-var: enrolling TPM2 keyslot (PCR 7)"
    # --unlock-key-file is required: without it systemd-cryptenroll prompts for a
    # passphrase and blocks forever in the initrd (no controlling tty), and the
    # raw binary key cannot pass through $PASSWORD (which cannot carry NULs).
    if systemd-cryptenroll --unlock-key-file="$KEY_FILE" \
            --tpm2-device=auto --tpm2-pcrs=7 "$VAR_DEV"; then
        echo "cryptsetup-var: TPM2 PCR-7 keyslot enrolled"
    else
        echo "cryptsetup-var: TPM2 PCR-7 enroll failed - retaining Argon2id keyslot (firmware measured boot may be unavailable)" >&2
    fi
    return 0
}

# Grow the LUKS container to fill the partition (e.g. after avocado-grow-var).
# Only the dm-crypt mapping is resized here; the btrfs filesystem is grown at
# mount time via the x-systemd.growfs option on /var (btrfs resize is an online,
# mounted-fs-only ioctl and cannot run against the not-yet-mounted mapper in the
# initrd).
maybe_resize() {
    PARTITION_SECTORS=$(blockdev --getsz "$VAR_DEV")
    DATA_OFFSET=$(dmsetup table "$MAP_NAME" 2>/dev/null | awk '{print $8}')
    if [ -z "$DATA_OFFSET" ]; then
        # dmsetup missing, or the table query failed/returned nothing. /var is
        # already open and formatted at this point - skip the resize rather
        # than let a malformed arithmetic expression fail the unit on the
        # last step of an otherwise-successful unlock.
        echo "cryptsetup-var: could not read dm-crypt data offset - skipping resize check" >&2
        return 0
    fi
    DM_SECTORS=$(blockdev --getsz "$MAPPER")
    EXPECTED_DM=$(( PARTITION_SECTORS - DATA_OFFSET ))
    if [ "$DM_SECTORS" -lt "$EXPECTED_DM" ]; then
        echo "cryptsetup-var: resizing LUKS container to fill partition"
        cryptsetup resize --key-file "$KEY_FILE" "$MAP_NAME"
    fi
}

# Encrypt a pre-seeded plaintext filesystem in place instead of formatting over
# it. Provisioning flashes the var btrfs `avocado build` produced (subvolumes,
# var_files, primed container images); with a device-generated key that image
# cannot be encrypted on the host, so first boot converts it here.
#
# LUKS2 needs a header in front of the data, so `--reduce-device-size 32M`
# shifts the data forward by 32 MiB, and `--device-size` names the DATA to
# convert - the filesystem's own size, not the filesystem plus the shift.
# cryptsetup adds the shift itself and refuses when data + 32 MiB exceeds the
# partition ("Reduced data size is larger than real device size"), which is
# exactly the situation on a freshly flashed partition sized to the image once
# the filesystem has been shrunk to make the 32 MiB. Confining the work to the
# filesystem also means only the data that exists gets encrypted; maybe_resize
# then grows the mapping to the partition on the following boots.
#
# Interrupted mid-way (power cut), LUKS2 records the reencryption in its
# metadata; open_var resumes it before opening. A filesystem whose size cannot
# be read gets the whole-partition reencryption instead - slower, still correct.
#
# A /var that has already been GROWN to fill the partition (a deployed device
# whose OTA turns encryption on) has no free tail for the header. btrfs can
# shrink online, so give the header its 32 MiB back first: mount, resize by
# the deficit, unmount, then reencrypt as usual. Anything else about the
# migration is the same; it just starts from a filesystem that no longer ends
# at the partition's last sector.
btrfs_total_bytes() {
    btrfs inspect-internal dump-super "$VAR_DEV" 2>/dev/null | awk '/^total_bytes/{print $2}'
}

# Shrink to what is actually allocated (plus room to relocate), not just by the
# 32 MiB the header needs: reencrypt converts the filesystem's full extent, and a
# /var that x-systemd.growfs has grown to fill a 30 GB partition would otherwise
# take many minutes to convert 200 MB of data. growfs grows it back at the first
# mount of the mapping.
#
# The yardstick is "Device allocated" (chunk space), not "Used": a shrink must
# relocate every chunk that lies past the new end into space inside it, and a
# filesystem this size allocates 1 GiB data chunks and 2 x 256 MiB DUP metadata
# chunks - asking for used+slack got "No space left on device" on the board.
# Allocated + 1.5 GiB leaves one full chunk set to relocate into. If btrfs still
# refuses, fall back to the minimal 32 MiB shrink rather than fail the unlock.
shrink_btrfs_for_header() {
    shrink_mib="$1"
    mnt=/run/cryptsetup-var-shrink
    mkdir -p "$mnt"
    if ! mount -t btrfs "$VAR_DEV" "$mnt"; then
        echo "cryptsetup-var: cannot mount $VAR_DEV to shrink it - cannot encrypt in place" >&2
        exit 1
    fi
    alloc_bytes=$(btrfs filesystem usage -b "$mnt" 2>/dev/null | awk '/^ *Device allocated:/{print $3; exit}')
    total_bytes=$(btrfs_total_bytes)
    minimal="-${shrink_mib}M"
    resize_arg="$minimal"
    if [ -n "$alloc_bytes" ] && [ "$alloc_bytes" -gt 0 ] 2>/dev/null; then
        target_mib=$(( (alloc_bytes + 1610612736 + 1048575) / 1048576 ))
        minimal_mib=$(( total_bytes / 1048576 - shrink_mib ))
        if [ "$target_mib" -lt "$minimal_mib" ]; then
            resize_arg="${target_mib}M"
        fi
    fi
    echo "cryptsetup-var: btrfs on $VAR_DEV fills the partition - resizing it (${resize_arg}) to make room for the LUKS2 header and keep the conversion to the data in use"
    if ! btrfs filesystem resize "$resize_arg" "$mnt"; then
        if [ "$resize_arg" = "$minimal" ]; then
            umount "$mnt"
            echo "cryptsetup-var: btrfs refused to resize to ${resize_arg} (tail in use or too full) - cannot encrypt in place" >&2
            exit 1
        fi
        echo "cryptsetup-var: btrfs refused ${resize_arg}; shrinking by the 32 MiB header only (the whole filesystem will be converted)" >&2
        if ! btrfs filesystem resize "$minimal" "$mnt"; then
            umount "$mnt"
            echo "cryptsetup-var: btrfs refused to shrink by ${shrink_mib} MiB (tail in use or too full) - cannot encrypt in place" >&2
            exit 1
        fi
    fi
    umount "$mnt"
}

encrypt_in_place() {
    fstype="$1"
    part_bytes=$(blockdev --getsize64 "$VAR_DEV")
    fs_bytes=""
    if [ "$fstype" = "btrfs" ] && command -v btrfs >/dev/null 2>&1; then
        fs_bytes=$(btrfs_total_bytes)
        if [ -n "$fs_bytes" ] && [ "$fs_bytes" -gt 0 ] 2>/dev/null \
           && [ $(( part_bytes - fs_bytes )) -lt 33554432 ]; then
            shrink_btrfs_for_header $(( (33554432 - (part_bytes - fs_bytes) + 1048575) / 1048576 ))
            fs_bytes=$(btrfs_total_bytes)
        fi
    fi
    size_opt=""
    if [ -n "$fs_bytes" ] && [ "$fs_bytes" -gt 0 ] 2>/dev/null; then
        # The data to convert is the filesystem, rounded up to whole MiB; it and
        # the 32 MiB shift must still fit the partition.
        want_mib=$(( (fs_bytes + 1048575) / 1048576 ))
        if [ $(( want_mib * 1048576 + 33554432 )) -le "$part_bytes" ]; then
            size_opt="--device-size ${want_mib}M"
        fi
    fi
    if [ -z "$size_opt" ] && [ $(( part_bytes - 33554432 )) -lt "${fs_bytes:-0}" ]; then
        echo "cryptsetup-var: $fstype on $VAR_DEV leaves no 32 MiB for a LUKS header - cannot encrypt in place" >&2
        exit 1
    fi
    # Tell whoever is watching the console what is about to happen: a seeded
    # /var can be tens of GiB, so this step can run for many minutes with
    # nothing else on screen. It is a one-time migration and resumable after a
    # power cut (resume_reencrypt). Periodic progress needs cryptsetup >= 2.4.
    if [ -n "$size_opt" ]; then work_mib=$want_mib; else work_mib=$(( part_bytes / 1048576 )); fi
    progress_opt=""
    if cryptsetup --help 2>&1 | grep -q -- --progress-frequency; then
        progress_opt="--progress-frequency 30"
    fi
    echo "cryptsetup-var: first boot - encrypting existing $fstype on $VAR_DEV in place${size_opt:+ ($size_opt)}"
    echo "cryptsetup-var: ${work_mib} MiB to convert - one-time migration, resumes after a power cut${progress_opt:+, progress every 30 s}"
    # shellcheck disable=SC2086 # size_opt / progress_opt are two words on purpose
    cryptsetup reencrypt --encrypt \
        --type luks2 \
        --cipher aes-xts-plain64 \
        --key-size 512 \
        --hash sha256 \
        --reduce-device-size 32M \
        $size_opt \
        $progress_opt \
        --key-file "$KEY_FILE" \
        --batch-mode \
        "$VAR_DEV"
}

# Resume a reencryption a previous boot did not finish. Idempotent: fails fast
# when no reencryption is recorded, which is the normal case.
resume_reencrypt() {
    if cryptsetup luksDump "$VAR_DEV" 2>/dev/null | awk '/online-reencrypt/{f=1} END{exit !f}'; then
        echo "cryptsetup-var: resuming interrupted reencryption on $VAR_DEV"
        cryptsetup reencrypt --resume-only --key-file "$KEY_FILE" --batch-mode "$VAR_DEV"
    fi
}

# 0. An explicitly required engine must be usable before anything is touched.
check_required_hardware

# 1. Ensure the LUKS2 container exists: encrypt a flashed filesystem in place,
#    or format a blank partition on first boot.
cryptsetup isLuks "$VAR_DEV" 2>/dev/null || {
    existing_fs=$(blkid -p -s TYPE -o value "$VAR_DEV" 2>/dev/null || true)
    if [ -n "$existing_fs" ]; then
        encrypt_in_place "$existing_fs"
    else
        echo "cryptsetup-var: first boot - formatting $VAR_DEV as LUKS2"
        cryptsetup luksFormat \
            --type luks2 \
            --cipher aes-xts-plain64 \
            --key-size 512 \
            --hash sha256 \
            --key-file "$KEY_FILE" \
            --batch-mode \
            "$VAR_DEV"
    fi
}

# 2. Ensure it is open as /dev/mapper/var (finishing any interrupted
#    reencryption first - the Argon2id key is the only one it can have then).
ensure_tpm2_unlocked
[ -b "$MAPPER" ] || { resume_reencrypt; open_var; }

# 3. Ensure a filesystem exists (self-heal a first boot interrupted before mkfs).
ensure_fs

# 4. Ensure the hardware-bound keyslots exist (best-effort; self-heal / late
#    enroll): a vendor key engine where one is installed, a TPM2 PCR-7 slot
#    where a TPM is present.
ensure_hwkey_enroll
ensure_tpm2_enroll
retire_derived_keyslot

# 5. Grow the container to fill the partition if it was expanded.
maybe_resize

# 6. Publish posture for userspace to pick up. Runs after the enrolls so a
# first boot reports the token it just enrolled rather than the absence it saw
# on open.
write_posture

echo "cryptsetup-var: $MAPPER ready"
