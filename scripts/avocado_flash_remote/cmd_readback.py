"""The ``readback`` subcommand: read what the test image left behind.

Mounts the profile's data partition READ-ONLY, copies the persistent journal
and boot logs into ``out_dir``, unmounts, compares BootOrder with the
reference recorded before the run and PRINTS (never runs) the cleanup
commands. The only ops verbs used are the read verbs plus ``mount`` (always
``-o ro``) and ``umount``; copies go through the injected ``copier`` and
stay under ``out_dir``. A missing journal is a recorded result, not an error.

Data partition lookup rule: the explicit ``data_partition_name`` argument
wins; otherwise the profile's image role ``var`` names a partition number,
and that number is looked up in the layout table for its partition name
(the shipped Jetson profile: var -> partition 16 -> DATAPART_EXPAND).

Port of the bash kit's readback.sh (sequence pinned by the golden call log,
cases ``window:rb-*``).

Standard library only (ships to a board running Python 3.10).
"""

from __future__ import annotations

import glob
import os
import posixpath
import re
import shutil
import stat
from dataclasses import dataclass, field

from .arm import boot_next_of, boot_order_of
from .ops import OpsError
from .state import LOCK_NAME, TERMINAL, LockHeld, OnBoardLock, load_state

DATA_ROLE = "var"
NO_JOURNAL_LINE = "the test image wrote no persistent journal"
RAM_FSTYPES = ("tmpfs", "ramfs")
# The target's own image is untrusted: nothing on it may be executed, honoured as a device node or run setuid.
MOUNT_OPTIONS = "ro,nosuid,nodev,noexec"
# The copy lands in RAM-backed /run beside the staged images. Refuse a source bigger than the free space
# minus a reserve, or bigger than a fixed cap, whichever is smaller.
COPY_RESERVE = 64 * 1024 * 1024
COPY_CAP = 256 * 1024 * 1024
_ABSENT_RE = re.compile(r"No such file or directory", re.IGNORECASE)


class ReadbackError(Exception):
    """The data partition cannot be determined from the profile."""


@dataclass
class ReadbackResult:
    exit_code: int
    found_journal: bool = False
    lines: list = field(default_factory=list)


def resolve_data_partition(profile, data_partition_name=None) -> str:
    """Name of the partition holding the journal; see the module docstring."""
    if data_partition_name:
        return data_partition_name
    image = profile.images.get(DATA_ROLE) if profile.images else None
    if image is None:
        raise ReadbackError(
            f"profile has no '{DATA_ROLE}' image role; pass data_partition_name"
        )
    for part in profile.layout.params["table"]:
        if part["number"] == image.partition:
            return part["name"]
    raise ReadbackError(f"partition {image.partition} is not in the layout table")


def _under(path, root) -> bool:
    return path == root or path.startswith(root + os.sep)


def make_guarded_copier(out_dir, mount_dir=None, note=None):
    """Default copier: copy a file or tree, never following a symlink.

    The mounted image is untrusted and this runs privileged, so a symlink in it must not pull a file
    from the live system into ``out_dir``. Symlinks and special files are skipped and noted; a source
    that is not under ``mount_dir`` (after resolving its parent directory) is refused; the destination
    must stay under ``out_dir``.
    """
    root = os.path.realpath(out_dir)
    mount_root = os.path.realpath(mount_dir) if mount_dir is not None else None
    say = note or (lambda line: None)

    def check_dst(dst):
        real = os.path.realpath(dst)
        if not _under(real, root):
            raise ReadbackError(f"refusing to copy outside {out_dir}: {dst}")

    def copy_file(src, dst):
        try:
            fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError as exc:
            say(f"skipped {src}: cannot open without following symlinks ({exc.strerror})")
            return
        with os.fdopen(fd, "rb") as fin:
            if not stat.S_ISREG(os.fstat(fin.fileno()).st_mode):
                say(f"skipped {src}: not a regular file")
                return
            with open(dst, "wb") as fout:
                shutil.copyfileobj(fin, fout)
        
    def copy_tree(src, dst):
        os.makedirs(dst, exist_ok=True)
        with os.scandir(src) as it:
            entries = sorted(it, key=lambda e: e.name)
        for entry in entries:
            child, target = os.path.join(src, entry.name), os.path.join(dst, entry.name)
            mode = entry.stat(follow_symlinks=False).st_mode
            if stat.S_ISLNK(mode):
                say(f"skipped {child}: symlink")
            elif stat.S_ISDIR(mode):
                copy_tree(child, target)
            elif stat.S_ISREG(mode):
                copy_file(child, target)
            else:
                say(f"skipped {child}: not a regular file")

    def copy(src, dst):
        check_dst(dst)
        if mount_root is not None and not _under(os.path.realpath(os.path.dirname(src)), mount_root):
            raise ReadbackError(f"refusing to read outside {mount_dir}: {src}")
        mode = os.lstat(src).st_mode
        if stat.S_ISLNK(mode):
            say(f"skipped {src}: symlink")
        elif stat.S_ISDIR(mode):
            copy_tree(src, dst)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            copy_file(src, dst)

    return copy


def _default_logs(mnt):
    found = glob.glob(os.path.join(mnt, "log", "*")) + glob.glob(os.path.join(mnt, "emmc-test*"))
    return sorted(p for p in found if os.path.isfile(p) and not os.path.islink(p))


def _tree_size(paths) -> int:
    """Bytes in the regular files under ``paths``: lstat only, a symlink counts for nothing and is never followed.

    A path that is absent counts as zero; any other error propagates to the caller.
    """
    total = 0
    stack = list(paths)
    while stack:
        path = stack.pop()
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(st.st_mode):
            with os.scandir(path) as it:
                stack.extend(e.path for e in it)
        elif stat.S_ISREG(st.st_mode):
            total += st.st_size
    return total


def _free_bytes(path) -> int:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def _private_dir(makedirs, path):
    """Create ``path`` mode 0700 regardless of umask (the injected makedirs may not create anything)."""
    makedirs(path, mode=0o700, exist_ok=True)
    if os.path.isdir(path):
        # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
        os.chmod(path, 0o700)


def _nearest_existing(path) -> str:
    """The path itself, or its closest existing ancestor: the filesystem a new directory would land on."""
    p = os.path.abspath(path)
    while not os.path.lexists(p) and p != os.path.dirname(p):
        p = os.path.dirname(p)
    return p


def run_readback(ops, profile, *, state_dir=None, out=print, **kw) -> ReadbackResult:
    """Read back the data partition, but only while no write or restore can be running.

    With a ``state_dir`` the on-board flash lock is taken first (a held lock refuses) and the current run's
    state must be terminal or absent; a refusal returns exit 1 before any call touches the board, and an
    unreadable state returns exit 2. Without a ``state_dir`` (unit use) no gate runs.
    """
    if state_dir is None:
        return _run_readback(ops, profile, out=out, **kw)
    result = ReadbackResult(0)

    def say(line):
        result.lines.append(line)
        out(line)

    try:
        with OnBoardLock(os.path.join(state_dir, LOCK_NAME), run_id="readback", wait_seconds=0.0):
            loaded = load_state(state_dir)
            if loaded.status == "unparseable":
                return _not_examined(result, say, f"the run state is unreadable ({loaded.reason}); not mounting")
            if loaded.status == "ok" and loaded.state.phase not in TERMINAL:
                say(
                    f"ERROR: run {loaded.state.run_id} is in phase {loaded.state.phase}, not finished; "
                    "refusing to mount the data partition under it. Nothing mounted."
                )
                result.exit_code = 1
                return result
            return _run_readback(ops, profile, out=out, **kw)
    except LockHeld as e:
        say(f"ERROR: the on-board flash lock is held ({e}): a write or restore may be running. Nothing mounted.")
    except OSError as e:
        say(f"ERROR: cannot take the on-board flash lock under {state_dir}: {e}. Nothing mounted.")
    result.exit_code = 1
    return result


def _run_readback(
    ops,
    profile,
    *,
    mount_dir,
    out_dir,
    reference_boot_order,
    data_partition_name=None,
    fstype="btrfs",
    copier=None,
    list_logs=None,
    makedirs=os.makedirs,
    nearest_existing=None,
    require_ram_out=True,
    is_mountpoint=os.path.ismount,
    free_bytes=_free_bytes,
    tree_size=_tree_size,
    reserve=COPY_RESERVE,
    cap=COPY_CAP,
    out=print,
) -> ReadbackResult:
    result = ReadbackResult(0)

    def say(line):
        result.lines.append(line)
        out(line)

    copier = copier or make_guarded_copier(out_dir, mount_dir, lambda line: say(line))
    list_logs = list_logs or _default_logs
    disk = profile.target.device
    label = resolve_data_partition(profile, data_partition_name)

    if profile.arm.strategy == "none":
        say("boot variables: not applicable (arm strategy none)")
    else:
        try:
            efi = ops.efibootmgr_list()
        except OpsError as e:
            say(f"TARGET NOT EXAMINED: efibootmgr -v failed: {e}")
            result.exit_code = 2
            return result
        current = boot_order_of(efi)
        nxt = boot_next_of(efi)
        say("== boot variables (efibootmgr -v) ==")
        say(f"BootNext   : {nxt or '<unset>'}")
        say(f"BootOrder  : {current or '<none>'}")
        if not reference_boot_order:
            say("no reference BootOrder recorded; not compared")
        elif current == reference_boot_order:
            say(f"BootOrder MATCHES the reference ({reference_boot_order})")
        else:
            say(f"BootOrder DIFFERS: now '{current or '<none>'}', reference '{reference_boot_order}'")
            result.exit_code = 1
        if nxt:
            say(f"NOTE: BootNext is still set ({nxt}): the one-shot boot did not consume it")

    try:
        ops.lsblk_disks()
        listing_text = ops.lsblk(disk).text.rstrip("\n")
    except OpsError as e:
        return _not_examined(result, say, f"lsblk failed: {e}")
    say(f"== lsblk {disk} ==")
    say(listing_text)

    say("")
    say(f"== {label}, mounted read-only on {mount_dir} ==")
    try:
        parts = ops.lsblk(disk, columns="NAME,PARTLABEL").text.splitlines()
    except OpsError as e:
        return _not_examined(result, say, f"lsblk failed: {e}")
    node = re.compile(rf"^{re.escape(posixpath.basename(disk))}p?\d+$")
    cands = []
    for row in parts:
        cols = row.split()
        if len(cols) == 2 and cols[1] == label and node.match(cols[0]):
            cands.append("/dev/" + cols[0])
    if len(cands) != 1:
        say(f"ERROR: expected exactly one {label} partition on {disk}, found {len(cands)}; not mounting")
        result.exit_code = 1
        _cleanup_hints(say, mount_dir, out_dir)
        return result
    part = cands[0]

    # Ask what the output lands on BEFORE creating anything: a refused run leaves no directory behind.
    try:
        fs = ops.findmnt_fstype((nearest_existing or _nearest_existing)(out_dir)).text.strip().splitlines()
    except OpsError as e:
        return _not_examined(result, say, f"findmnt failed: {e}")
    outfs = fs[0] if fs else ""
    if require_ram_out and outfs not in RAM_FSTYPES:
        say(f"ERROR: {out_dir} is on '{outfs or 'unknown'}', not tmpfs; the logs must not land on the live system's disk. Not mounting.")
        result.exit_code = 1
        _cleanup_hints(say, mount_dir, out_dir)
        return result

    if is_mountpoint(mount_dir):
        say(f"ERROR: {mount_dir} is already a mount point; not stacking a second mount on it")
        result.exit_code = 1
        _cleanup_hints(say, mount_dir, out_dir)
        return result

    _private_dir(makedirs, mount_dir)
    _private_dir(makedirs, out_dir)
    mounted = False
    done = 0
    try:
        ops.mount(part, mount_dir, options=MOUNT_OPTIONS, fstype=fstype)
        mounted = True
        say(f"mounted {part} read-only")
        ops.run_read(["ls", "-la", mount_dir])
        journal = posixpath.join(mount_dir, "log", "journal")
        listing = ops.run_read(["ls", "-laR", journal], check=False)
        if listing.rc == 0:
            result.found_journal = True
        elif _ABSENT_RE.search(listing.stderr or ""):
            say(NO_JOURNAL_LINE)
        else:
            # Permission denied, an I/O error or an unrecognised message is not a confirmed absence.
            first = (listing.stderr or "").strip().splitlines()[:1]
            say(f"TARGET NOT EXAMINED: listing {journal} failed (rc={listing.rc}): {first[0] if first else 'no message'}")
            result.exit_code = 2
            return result
        logs = list_logs(mount_dir)
        need = tree_size(([journal] if result.found_journal else []) + list(logs))
        free = free_bytes(_nearest_existing(out_dir))
        limit = max(min(cap, free - reserve), 0)
        if need > 0 and need > limit:
            say(
                f"ERROR: {need} bytes to copy exceeds the {limit} bytes allowed "
                f"(free {free}, reserve {reserve}, cap {cap}) on the filesystem holding {out_dir}: "
                "the journal is too large to copy into RAM-backed storage; not copying"
            )
            result.exit_code = 1
            _discard(out_dir)
        else:
            if result.found_journal:
                copier(journal, os.path.join(out_dir, "journal"))
                done += 1
                say(f"copied journal to {out_dir}/journal")
            # Each log keeps its path relative to the mount, so log/<name> and <name> cannot overwrite each other.
            dests = {"journal"}
            for f in logs:
                rel = os.path.relpath(f, mount_dir)
                if rel in dests:
                    raise ReadbackError(f"destination collision: {rel} would be written twice")
                dests.add(rel)
                copier(f, os.path.join(out_dir, rel))
                done += 1
            say(f"copied {len(dests) - 1} boot log file(s) to {out_dir}")
    except OpsError as e:
        say(f"ERROR: read-only mount or read of {part} failed: {e}")
        result.exit_code = 1
    except (OSError, ReadbackError) as e:
        say(f"ERROR: copy from {part} failed after {done} file(s): {e}")
        result.exit_code = 1
        _discard(out_dir)
    finally:
        if mounted:
            try:
                ops.umount(mount_dir)
            except OpsError as e:
                say(f"ERROR: umount {mount_dir} failed ({e}); the mount is still active: unmount it by hand")
                result.exit_code = result.exit_code or 1
    _cleanup_hints(say, mount_dir, out_dir)
    return result


def _not_examined(result, say, why):
    say(f"TARGET NOT EXAMINED: {why}")
    result.exit_code = 2
    return result


def _discard(path):
    """Remove a partial output directory this run created."""
    shutil.rmtree(path, ignore_errors=True)


def _cleanup_hints(say, mount_dir, out_dir):
    say("")
    say("== cleanup commands (printed, NOT run) ==")
    say(f"  umount {mount_dir}     # only if still mounted")
    say(f"  rmdir {mount_dir}")
    say(f"  rm -r {out_dir}     # the copied logs, once you have read them")
    say("  restore    # disarms the one-shot boot entry; it is not a rollback")


__all__ = [
    "NO_JOURNAL_LINE", "ReadbackError", "ReadbackResult", "resolve_data_partition",
    "make_guarded_copier", "run_readback",
]  # fmt: skip
