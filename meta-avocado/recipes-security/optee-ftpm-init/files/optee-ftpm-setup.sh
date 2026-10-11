#!/bin/sh
# Bring up the OP-TEE fTPM in the initramfs so /dev/tpm0 exists before
# cryptsetup-var's TPM2 PCR-7 enroll.
#
# The fTPM TA is embedded as an OP-TEE early TA (built into BL32 by meta-arm's
# optee-ftpm/optee-os wiring), but its NV secure storage is REE-FS on every
# machine that runs this today (see optee-ftpm-init.bb for why, per machine),
# and REE-FS is serviced by tee-supplicant in userspace. So:
#   * tpm_ftpm_tee is a module (not built-in): loaded here, after tee-supplicant,
#     rather than probing at kernel init when the supplicant isn't running yet.
#   * the fTPM NV (the seed the SRK derives from) is kept on the recovery
#     partition rather than the initramfs tmpfs, at tee-supplicant's compiled-in
#     path /var/lib/tee.
#
# Reboot-survival caveat: OP-TEE's secure storage anti-rollback needs an RPMB
# counter, and no machine running this uses one yet - qemuarm64 has no RPMB at
# all, and the i.MX93 OP-TEE has the hardware but is not built with
# CFG_RPMB_FS=y. So the seal is created on first boot and /var falls back to
# Argon2id on reboot. See optee-ftpm-init.bb.
set -u

# The store partition named by @TEE_STORE_DEV@ (a /dev/disk/by-partlabel/
# path), looked up on one disk only: $1 is the disk the root filesystem was
# found on (e.g. mmcblk0), passed by a platform initrd that knows it. A
# partlabel symlink names whichever disk udev saw last when several carry the
# label (an eMMC and an NVMe that were both provisioned), and the fTPM's NV
# must not land on, or move to, a disk the device did not boot from. Prints
# the device; prints nothing when the label is not on that disk.
store_on_disk() {
    _disk=$1 _label=${2##*/}
    for _p in "${AVOCADO_SYSFS:-/sys}/block/$_disk/$_disk"*; do
        [ -f "$_p/uevent" ] || continue
        if grep -qx "PARTNAME=$_label" "$_p/uevent"; then
            echo "/dev/${_p##*/}"
            return 0
        fi
    done
}

# How to start the supplicant. Prints "survive" or "legacy". A real root that ships optee-client starts its own supplicant
# (tee-supplicant.service, or the tee-supplicant@.service template that the udev rule starts) once the initrd one is gone, and
# that one needs /dev/teepriv0: a daemon that outlives the switch keeps the device, the second open fails with EBUSY and the
# unit fails. So the daemon is kept alive across the switch ("survive") only when the real root, mounted at $1, is visible
# and ships no supplicant unit. When the real root is not mounted yet, or ships one, keep the plain daemon ("legacy"): it
# dies at the switch and the real root's supplicant takes over, which is how images with optee-client in the rootfs work.
supplicant_mode() {
    _root=${1:-/sysroot}
    [ -d "$_root/usr/lib/systemd/system" ] || { echo legacy; return 0; }
    for _u in tee-supplicant.service 'tee-supplicant@.service'; do
        for _d in usr/lib/systemd/system lib/systemd/system etc/systemd/system; do
            [ -e "$_root/$_d/$_u" ] && { echo legacy; return 0; }
        done
    done
    echo survive
}

# Move every tee-supplicant process that was started with an '@' argv[0] into the root cgroup, out of the cgroup of the
# unit that started it. When the real root has no copy of that unit, its systemd stops it as a stub at the switch, and
# that stop kills what is left in the unit's cgroup. A tee-supplicant without the '@' (one that udev or another unit started
# first) is left alone: systemd kills it at the switch whichever cgroup it is in, so moving it would only make the log lie.
# $1 is the proc directory and $2 the cgroup.procs file of the root cgroup (arguments so a host test can point both at a
# fake). Prints each pid it moved; returns 1 when no such process was found or moved, or when $2 does not exist (a
# cgroup v1 layout has no such file, and a plain `echo >` would create one and report success). No pgrep here: the
# initramfs is minimal.
supplicant_to_root_cgroup() {
    _proc=${1:-/proc} _cg=${2:-/sys/fs/cgroup/cgroup.procs} _moved=0
    [ -f "$_cg" ] || return 1
    for _c in "$_proc"/[0-9]*/comm; do
        { read -r _name < "$_c"; } 2>/dev/null || continue
        [ "$_name" = tee-supplicant ] || continue
        _pid=${_c#"$_proc"/}
        _pid=${_pid%/comm}
        _argv0=
        { read -r _argv0 < "$_proc/$_pid/cmdline"; } 2>/dev/null
        case $_argv0 in @*) ;; *) continue ;; esac
        if echo "$_pid" > "$_cg"; then
            echo "$_pid"
            _moved=1
        fi
    done
    [ "$_moved" = 1 ]
}

# Start tee-supplicant through tee-supplicant-initrd.service, then move the daemon out of that unit's cgroup. Prints the
# pids it moved. Returns 2 when the unit could not be started, 1 when the daemon could not be found or moved, 0 otherwise.
# $1 and $2 are handed to supplicant_to_root_cgroup.
start_supplicant() {
    systemctl start tee-supplicant-initrd.service || return 2
    supplicant_to_root_cgroup "${1:-/proc}" "${2:-/sys/fs/cgroup/cgroup.procs}" || return 1
}
[ "${OPTEE_FTPM_SETUP_LIB:-}" = 1 ] && return 0

# Surface progress on the console (the initrd journal is not forwarded here).
exec >/dev/console 2>&1

# Fail-closed pre-flight: refuse before any privileged action (mount, format,
# tee-supplicant, modprobe) if either (a) this device's base image never
# declared ftpm, or (b) the kernel cannot actually deliver OP-TEE. These two
# refusal paths must stay distinguishable per design.md A6 - a declaration
# problem and a kernel problem need different fixes, so collapsing them into
# one message would hide which side to fix. Mirrors cryptsetup-var.sh's
# check_capability_declared/check_dmcrypt_available shape.
CAPABILITIES_FILE="/etc/avocado-security-capabilities"
REQUIRED_CAPABILITY="ftpm"

check_capability_declared() {
    if [ ! -f "$CAPABILITIES_FILE" ]; then
        echo "optee-ftpm: $CAPABILITIES_FILE is absent - this device's base image never declared $REQUIRED_CAPABILITY" >&2
        exit 1
    fi
    declared="$(cat "$CAPABILITIES_FILE")"
    for token in $declared; do
        [ "$token" = "$REQUIRED_CAPABILITY" ] && return 0
    done
    echo "optee-ftpm: $REQUIRED_CAPABILITY is missing from this device's AVOCADO_SECURITY_CAPABILITIES declaration (declares: ${declared:-<empty>})" >&2
    exit 1
}

check_optee_available() {
    [ -e /sys/bus/tee ] && return 0
    echo "optee-ftpm: this device's kernel cannot deliver OP-TEE - fTPM is unavailable" >&2
    exit 1
}

check_capability_declared
check_optee_available

# Substituted from OPTEE_FTPM_TEE_STORE_DEV by optee-ftpm-init.bb.
TEE_DEV=@TEE_STORE_DEV@
BOOT_DISK=${1:-}
if [ -n "$BOOT_DISK" ] && [ "${TEE_DEV#/dev/disk/by-partlabel/}" != "$TEE_DEV" ]; then
    TEE_DEV=$(store_on_disk "$BOOT_DISK" "$TEE_DEV")
    [ -n "$TEE_DEV" ] || { echo "optee-ftpm: no @TEE_STORE_DEV@ partition on the boot disk $BOOT_DISK, skipping fTPM bring-up"; exit 0; }
    echo "optee-ftpm: TEE store $TEE_DEV (on the boot disk $BOOT_DISK)"
fi
[ -b "$TEE_DEV" ] || { echo "optee-ftpm: no TEE store partition at $TEE_DEV, skipping fTPM bring-up"; exit 0; }

# Mount the persistent TEE store, formatting it (btrfs) on first boot.
#
# btrfs-tools is an explicit RDEPENDS of this recipe, NOT something inherited
# from /var's own tooling - an earlier revision of this comment claimed the
# latter, and it only holds when the encrypted-var DISTRO_FEATURE pulls
# cryptsetup-var in. Built without it, mkfs.btrfs was simply absent and the
# format below failed. See optee-ftpm-init.bb.
#
# tee-supplicant was built with TEE_FS_PARENT_PATH=/var/lib/tee, so that exact
# path must be the persistent mount or the fTPM's NV lands on the initramfs
# tmpfs and is lost on reboot. The mount is made on the initramfs /var and is
# covered by the real /var moments later, which is why /var/lib/tee does not
# exist on a running system - see optee-ftpm-setup.service for the ordering
# that makes that sequence deterministic instead of a race.
TEE_STORE=/var/lib/tee
mkdir -p "$TEE_STORE"
# Always mount with the store's type: an untyped mount of a blank partition
# probes every filesystem, and a failing probe can take the kernel down (the
# 6.18 erofs probe double-frees in put_fs_context).
if ! mount -t btrfs "$TEE_DEV" "$TEE_STORE" 2>/dev/null; then
    # Probe before formatting, same intent as cryptsetup-var.sh's ensure_fs:
    # mount can fail for reasons other than "no filesystem yet" (a dirty btrfs
    # needing recovery, a foreign signature), and -f would clobber the recovery
    # partition's real contents in exactly that case.
    #
    # Test the TYPE value, NOT blkid's exit status. cryptsetup-var.sh can key on
    # the status because it probes /dev/mapper/var, a dm device that carries no
    # partition-table metadata - with no filesystem there, blkid finds nothing
    # at all. This probes a GPT PARTITION, where blkid -p still reports
    # PART_ENTRY_* and exits 0 on a completely blank partition. Keying on the
    # status therefore reported "has a filesystem" unconditionally, the format
    # path below was unreachable on every board, and the fTPM could never come
    # up on a first boot. Verified against a blank GPT partition on a loop
    # device: `blkid -p` and `blkid -p -u filesystem` both exit 0, while
    # `blkid -p -s TYPE -o value` prints nothing - so emptiness of the value is
    # the only reliable discriminator here.
    if [ -n "$(blkid -p -s TYPE -o value "$TEE_DEV" 2>/dev/null)" ]; then
        echo "optee-ftpm: $TEE_DEV has a filesystem but would not mount;" \
             "skipping fTPM bring-up (/var will fall back to Argon2id)" >&2
        exit 0
    fi
    echo "optee-ftpm: first boot - formatting TEE store on $TEE_DEV"
    # If we cannot format and mount the persistent store, do not fall through:
    # tee-supplicant would keep the fTPM NV on the initramfs tmpfs, silently
    # non-persistent. Skip fTPM bring-up instead so /var takes its Argon2id path.
    if ! mkfs.btrfs -M -L teestore "$TEE_DEV" || ! mount -t btrfs "$TEE_DEV" "$TEE_STORE"; then
        echo "optee-ftpm: could not prepare persistent TEE store on $TEE_DEV;" \
             "skipping fTPM bring-up (/var will fall back to Argon2id)" >&2
        exit 0
    fi
fi

# tee-supplicant services the fTPM's REE-FS storage (and the RPC in general). When the real root ships no supplicant of
# its own it has to outlive the switch to the real root, which a plain `tee-supplicant -d` does not: systemd sends
# SIGTERM to every process left in the initrd at the switch, except one whose argv[0] starts with '@'. So in that case
# start it through tee-supplicant-initrd.service, which runs it with an '@' argv[0], then move the daemon out of that
# unit's cgroup (a real root without the unit stops it as a stub). See supplicant_mode for when this applies.
if [ "$(supplicant_mode /sysroot)" = survive ]; then
    moved=$(start_supplicant)
    case $? in
    0) echo "optee-ftpm: tee-supplicant started (pid $moved) and moved out of the unit's cgroup" ;;
    2)
        # Do not skip the fTPM bring-up over this: the plain start below is what this script always did.
        echo "optee-ftpm: could not start tee-supplicant-initrd.service; starting a plain tee-supplicant" >&2
        tee-supplicant -d
        ;;
    *)
        echo "optee-ftpm: could not move tee-supplicant out of the unit's cgroup;" \
             "it may not survive the switch to the real root" >&2
        ;;
    esac
else
    echo "optee-ftpm: the real root has its own supplicant (or is not mounted yet); starting a plain tee-supplicant"
    tee-supplicant -d
fi

# Load the fTPM driver now that storage is available; it opens a session to the
# embedded early TA and registers /dev/tpm0.
modprobe tpm_ftpm_tee || true

# Give the chip time to appear so the enroll finds it. Whole-second sleep,
# not fractional: busybox's sleep applet needs FEATURE_FANCY_SLEEP to accept
# a fractional argument, and this minimal initramfs's busybox is not
# guaranteed to have it - an unsupported "0.1" errors out instantly, the
# loop spins its iterations with no real wait, and the chip is reported
# missing on a board where it would have appeared. cryptsetup-var.sh's own
# TPM wait uses whole seconds for the same reason.
i=0
while [ ! -e /dev/tpm0 ] && [ "$i" -lt 10 ]; do i=$((i + 1)); sleep 1; done
if [ -e /dev/tpm0 ]; then
    echo "optee-ftpm: /dev/tpm0 ready"
else
    echo "optee-ftpm: /dev/tpm0 did not appear - /var will fall back to Argon2id" >&2
fi
