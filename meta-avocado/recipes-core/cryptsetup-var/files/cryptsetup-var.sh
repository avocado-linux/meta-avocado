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

    {
        echo "VAR_UNLOCK_METHOD=${VAR_UNLOCK_METHOD}"
        echo "VAR_TPM2_TOKEN=${_tpm2_token}"
        echo "VAR_TPM_DEVICE=${_tpm_dev}"
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
    if has_tpm2_token; then
        # A token exists, so a TPM is expected. On a fast reboot we can reach the
        # open before udev has created /dev/tpm0 (seen ~9s in) and wrongly fall
        # back to Argon2id. Wait briefly for the device before deciding.
        i=0
        while [ ! -e /dev/tpm0 ] && [ "$i" -lt 15 ]; do i=$((i + 1)); sleep 1; done

        # The token open needs the libcryptsetup TPM2 plugin, not the
        # systemd-cryptenroll binary - so probe capability by just attempting it
        # and letting it fall through to the Argon2id recovery key on failure.
        if [ -e /dev/tpm0 ] && cryptsetup open --token-only "$VAR_DEV" "$MAP_NAME" 2>/dev/null; then
            echo "cryptsetup-var: opened via TPM2 token"
            VAR_UNLOCK_METHOD="tpm2"
            return 0
        fi
        echo "cryptsetup-var: TPM2 unseal unavailable - opening with the Argon2id recovery key" >&2
    fi

    if ! cryptsetup luksOpen --key-file "$KEY_FILE" "$VAR_DEV" "$MAP_NAME" 2>/dev/null; then
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

# Ensure a TPM2 keyslot sealed to PCR 7 exists, keeping the Argon2id keyslot
# (slot 0) as the recovery path. Idempotent and best-effort: skips when a token
# already exists, when no TPM is present, or when systemd-cryptenroll is absent.
# A failed enroll (e.g. firmware without measured boot) leaves the volume
# encrypted under Argon2id rather than failing the unit. Running on every boot
# also enrolls a device whose first boot happened before /dev/tpm0 existed.
ensure_tpm2_enroll() {
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

# 4. Ensure a TPM2 PCR-7 keyslot exists (best-effort; self-heal / late enroll).
ensure_tpm2_enroll

# 5. Grow the container to fill the partition if it was expanded.
maybe_resize

# 6. Publish posture for userspace to pick up. Runs after ensure_tpm2_enroll so a
# first boot reports the token it just enrolled rather than the absence it saw
# on open.
write_posture

echo "cryptsetup-var: $MAPPER ready"
