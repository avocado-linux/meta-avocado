"""The ``restore`` subcommand: disarm and clean up, never a rollback.

Scope: remove the boot entry this tool created (matched by its recorded
number AND label) and the one-shot BootNext, verify the boot order still
equals the value recorded before any mutation, then remove the staging
directory. Partition table and image changes are NOT rolled back, and the
output says so. After a reboot into the test entry only staging is cleaned.

With missing or unparseable state it refuses; ``--emergency-disarm`` (plus an
acknowledgement) removes only entries carrying the profile's arm label and a
BootNext that points at one of them.

Standard library only (ships to a board running Python 3.10).
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .arm import Arm, ArmRecord, _field, boot_next_of, boot_order_of, entries_with_label
from .ops import OpsError
from .state import describe_recovery, load_state

NOTE_LINE = "note: restore does not roll back partition table or image changes"
_ROLLED_PHASES = ("table-written", "image-writing", "image-written", "verified", "armed", "complete")
_MIN_PARTS = 3  # "/", "run", "dir"


class StagingRefused(Exception):
    """The staging path failed a safety guard; nothing was removed."""


@dataclass
class RestoreResult:
    exit_code: int
    actions: list = field(default_factory=list)
    lines: list = field(default_factory=list)


def check_staging_path(path, expected) -> None:
    """Refuse anything but the profile's own staging dir (no symlink, not shallow)."""
    if not path or not expected or path != expected:
        raise StagingRefused(f"{path!r} is not the profile staging dir {expected!r}")
    p = Path(path)
    if not p.is_absolute() or len(p.parts) < _MIN_PARTS:
        raise StagingRefused(f"{path!r} is too shallow to remove")
    if p.is_symlink():
        raise StagingRefused(f"{path!r} is a symlink")


def make_guarded_rmtree(expected):
    def remove(path):
        check_staging_path(str(path), expected)
        shutil.rmtree(path)

    return remove


def _entry_present(text, number) -> bool:
    return re.search(rf"^Boot{re.escape(number)}\b", text, re.IGNORECASE | re.MULTILINE) is not None


def run_restore(
    ops,
    profile,
    *,
    state_dir,
    staging_dir,
    ack_run_id=None,
    emergency_disarm=False,
    remove_tree=None,
    out=print,
) -> RestoreResult:
    result = RestoreResult(0)
    expected_staging = profile.staging.dir
    if remove_tree is None:
        remove_tree = make_guarded_rmtree(expected_staging)

    def say(line):
        result.lines.append(line)
        out(line)

    def finish(code, note):
        if note:
            say(NOTE_LINE)
        result.exit_code = code
        return result

    def clean_staging() -> bool:
        if not os.path.lexists(staging_dir):
            say(f"staging {staging_dir} not present; nothing to remove")
            return True
        try:
            check_staging_path(str(staging_dir), expected_staging)
            remove_tree(staging_dir)
        except (StagingRefused, OSError) as e:
            say(f"staging NOT removed: {e}")
            return False
        result.actions.append(f"removed staging {staging_dir}")
        say(f"removed staging {staging_dir}")
        return True

    loaded = load_state(state_dir)
    label = profile.arm.params.get("label", "") if profile.arm.params else ""

    if emergency_disarm:
        return _emergency(ops, label, ack_run_id, loaded, say, result, finish)

    if loaded.status == "unparseable":
        say(f"refusing: run state is unreadable: {loaded.reason}")
        say("no boot entry or staging was touched")
        say(
            "inspect `efibootmgr -v` by hand, or run `restore --emergency-disarm "
            "--ack <text>` to remove only entries labelled "
            f"{label!r} and the one-shot setting"
        )
        return finish(1, True)

    if loaded.status == "absent":
        say("no run state found: nothing to restore for boot entries")
        ok = clean_staging()
        return finish(0 if ok else 1, True)

    state = loaded.state
    phases = [p.get("phase") for p in state.data.get("phases_done", [])]
    note = any(p in _ROLLED_PHASES for p in phases)
    say(f"run {state.run_id} phase {state.phase}: {describe_recovery(state)}")
    armed = state.data.get("armed")
    if not isinstance(armed, dict) or not (armed.get("entry_number") or armed.get("next_armed")):
        say("no boot entry was armed by this run; no efibootmgr calls made")
        ok = clean_staging()
        return finish(0 if ok else 1, note)

    record = ArmRecord.from_dict(armed)
    try:
        live = ops.efibootmgr_list()
        current = _field(live, "BootCurrent").upper()
        if record.entry_number and current == record.entry_number.upper():
            say(
                f"BootCurrent is {current}: the board booted the test entry; "
                "boot entries left unchanged"
            )
            say(f"found BootOrder {boot_order_of(live)} BootNext {boot_next_of(live) or '(none)'}")
            ok = clean_staging()
            return finish(0 if ok else 1, note)

        notes = Arm().disarm(ops, record)
        for n in notes:
            result.actions.append(n)
            say(n)
        after = ops.efibootmgr_list()
    except OpsError as e:
        say(f"restore FAILED: {e}; staging kept, rerun `restore` after inspecting efibootmgr -v")
        return finish(1, note)

    problem = False
    if record.entry_number and _entry_present(after, record.entry_number):
        if record.entry_number.upper() not in entries_with_label(after, record.label):
            say(
                f"boot entry {record.entry_number} exists with a different label than "
                f"{record.label!r}; left alone"
            )
            problem = True
    now = boot_order_of(after)
    if record.preexisting_boot_order:
        if now == record.preexisting_boot_order:
            say(f"BootOrder {now} equals the recorded value")
        else:
            say(f"BootOrder {now!r} differs from recorded {record.preexisting_boot_order!r}; not changed")
            problem = True
    if problem:
        say("staging kept")
        return finish(1, note)
    ok = clean_staging()
    return finish(0 if ok else 1, note)


def _emergency(ops, label, ack, loaded, say, result, finish):
    if not ack:
        say("refusing: --emergency-disarm needs an acknowledgement (--ack <text>)")
        say(f"it removes only boot entries labelled {label!r} and BootNext if it points at one")
        return finish(1, True)
    if not label:
        say("refusing: the profile has no arm label to match")
        return finish(1, True)
    say(f"emergency disarm acknowledged ({ack}); run state: {loaded.status}")
    try:
        live = ops.efibootmgr_list()
        ours = entries_with_label(live, label)
        nxt = boot_next_of(live).upper()
        if nxt and nxt in ours:
            ops.efibootmgr_delete_next()
            result.actions.append(f"cleared BootNext {nxt}")
            say(f"cleared BootNext {nxt}")
        for num in ours:
            ops.efibootmgr_delete(num)
            result.actions.append(f"deleted boot entry {num}")
            say(f"deleted boot entry {num}")
    except OpsError as e:
        say(f"emergency disarm FAILED: {e}")
        return finish(1, True)
    if not ours:
        say(f"no boot entry labelled {label!r}; nothing removed")
    say("BootOrder and all other entries were not touched; staging was not touched")
    return finish(0, True)


__all__ = [
    "NOTE_LINE", "RestoreResult", "StagingRefused", "check_staging_path",
    "make_guarded_rmtree", "run_restore",
]  # fmt: skip
