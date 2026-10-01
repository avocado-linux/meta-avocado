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
from dataclasses import dataclass, field

from .arm import boot_next_of, boot_order_of
from .ops import OpsError

DATA_ROLE = "var"
NO_JOURNAL_LINE = "the test image wrote no persistent journal"
RAM_FSTYPES = ("tmpfs", "ramfs")


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


def make_guarded_copier(out_dir):
    """Default copier: copy a file or tree, refusing any destination outside out_dir."""
    root = os.path.realpath(out_dir)

    def copy(src, dst):
        real = os.path.realpath(dst)
        if real != root and not real.startswith(root + os.sep):
            raise ReadbackError(f"refusing to copy outside {out_dir}: {dst}")
        if os.path.isdir(src):
            shutil.copytree(src, dst, copy_function=shutil.copy2, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)

    return copy


def _default_logs(mnt):
    found = glob.glob(os.path.join(mnt, "log", "*")) + glob.glob(os.path.join(mnt, "emmc-test*"))
    return sorted(p for p in found if os.path.isfile(p))


def run_readback(
    ops,
    profile,
    *,
    state_dir=None,
    mount_dir,
    out_dir,
    reference_boot_order,
    data_partition_name=None,
    fstype="btrfs",
    copier=None,
    list_logs=None,
    makedirs=os.makedirs,
    require_ram_out=True,
    out=print,
) -> ReadbackResult:
    result = ReadbackResult(0)

    def say(line):
        result.lines.append(line)
        out(line)

    copier = copier or make_guarded_copier(out_dir)
    list_logs = list_logs or _default_logs
    disk = profile.target.device
    label = resolve_data_partition(profile, data_partition_name)

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

    ops.lsblk_disks()
    say(f"== lsblk {disk} ==")
    say(ops.lsblk(disk).text.rstrip("\n"))

    say("")
    say(f"== {label}, mounted read-only on {mount_dir} ==")
    parts = ops.lsblk(disk, columns="NAME,PARTLABEL").text.splitlines()
    node = re.compile(rf"^{re.escape(posixpath.basename(disk))}p?\d+$")
    cands = []
    for row in parts:
        cols = row.split()
        if len(cols) == 2 and cols[1] == label and node.match(cols[0]):
            cands.append("/dev/" + cols[0])
    if len(cands) != 1:
        say(f"ERROR: expected exactly one {label} partition on {disk}, found {len(cands)}; not mounting")
        result.exit_code = 1
        _cleanup_hints(say, mount_dir)
        return result
    part = cands[0]

    makedirs(mount_dir, exist_ok=True)
    makedirs(out_dir, exist_ok=True)
    fs = ops.findmnt_fstype(out_dir).text.strip().splitlines()
    outfs = fs[0] if fs else ""
    if require_ram_out and outfs not in RAM_FSTYPES:
        say(f"ERROR: {out_dir} is on '{outfs or 'unknown'}', not tmpfs; the logs must not land on the live system's disk. Not mounting.")
        result.exit_code = 1
        _cleanup_hints(say, mount_dir)
        return result

    mounted = False
    try:
        ops.mount(part, mount_dir, options="ro", fstype=fstype)
        mounted = True
        say(f"mounted {part} read-only")
        ops.run_read(["ls", "-la", mount_dir])
        journal = posixpath.join(mount_dir, "log", "journal")
        listing = ops.run_read(["ls", "-laR", journal], check=False)
        if listing.rc == 0:
            result.found_journal = True
            copier(journal, os.path.join(out_dir, "journal"))
            say(f"copied journal to {out_dir}/journal")
        else:
            say(NO_JOURNAL_LINE)
        copied = 0
        for f in list_logs(mount_dir):
            copier(f, os.path.join(out_dir, os.path.basename(f)))
            copied += 1
        say(f"copied {copied} boot log file(s) to {out_dir}")
    except OpsError as e:
        say(f"ERROR: read-only mount or read of {part} failed: {e}")
        result.exit_code = 1
    finally:
        if mounted:
            try:
                ops.umount(mount_dir)
            except OpsError as e:
                say(f"WARNING: umount {mount_dir} failed ({e}); unmount it by hand")
    _cleanup_hints(say, mount_dir)
    return result


def _cleanup_hints(say, mount_dir):
    say("")
    say("== cleanup commands (printed, NOT run) ==")
    say(f"  umount {mount_dir}     # only if still mounted")
    say(f"  rmdir {mount_dir}")
    say("  restore    # disarms the one-shot boot entry; it is not a rollback")


__all__ = [
    "NO_JOURNAL_LINE", "ReadbackError", "ReadbackResult", "resolve_data_partition",
    "make_guarded_copier", "run_readback",
]  # fmt: skip
