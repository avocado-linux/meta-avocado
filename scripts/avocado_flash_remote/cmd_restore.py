"""The ``restore`` subcommand: disarm and clean up, never a rollback.

Scope: clear the one-shot BootNext when it names the firmware entry this run
armed (matched by its recorded number AND label), verify the boot order still
equals the value recorded before any mutation, then remove the staging
directory. No boot entry is ever deleted: the entry is the firmware's own.
A BootNext already consumed by a boot is a note, not a failure. Partition table and image changes are NOT rolled back, and the
output says so. After a reboot into the test entry only staging is cleaned.

It takes the on-board flash lock first and refuses while another holder is
live, so it can never run against a write in progress. A run in a non-terminal
phase needs ``--ack-run RUN_ID`` naming that run. After a successful restore the
run's state is advanced to the terminal ``restored`` so a new plan and write
are accepted by the state gate (plan itself still refuses a target that has a
partition table when the profile sets ``require_empty``: restore wipes nothing).

With missing or unparseable state it refuses; ``--emergency-disarm`` (plus an
acknowledgement) clears only a BootNext that points at the entry carrying the
profile's entry label, and deletes nothing.

Standard library only (ships to a board running Python 3.10).
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .arm import Arm, ArmError, ArmRecord, _field, boot_next_of, boot_order_of, entries_with_label
from .ops import OpsError
from .cmd_status import _load_run
from .state import LOCK_NAME, TERMINAL, LoadResult, LockHeld, OnBoardLock, describe_recovery, load_state, transition

NOTE_LINE = "note: restore does not roll back partition table or image changes"
# How long --emergency-disarm waits for a holder of the flash lock before it prints
# the manual steps instead. The normal restore path never waits.
EMERGENCY_LOCK_WAIT = 15.0
_ROLLED_PHASES = (
    "table-writing", "table-written", "image-writing", "image-written", "verified", "arming", "armed", "complete",
)  # fmt: skip
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


def _lock_record(exc):
    raw = getattr(exc, "holder", "") or ""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _lock_holder(exc) -> str:
    data = _lock_record(exc)
    if data is None:
        return getattr(exc, "holder", "") or "an unknown holder"
    return f"pid {data.get('pid')} (run {data.get('run_id') or 'none'})"


def _holder_gone(exc) -> bool:
    """True only when the lock file names a pid and /proc says that process is not there.

    Anything else (a record that is missing, unparseable or names no integer pid) counts as a live
    holder: the lock is held, so a writer may be mid-write, and an unknown is never read as gone.
    """
    data = _lock_record(exc)
    pid = data.get("pid") if data else None
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    return not os.path.exists(f"/proc/{pid}")


def _live_holder_lines(holder) -> list:
    return [
        f"the on-board flash lock is held by {holder} and did not clear in time",
        "that holder is alive or cannot be shown to be gone: a write may be changing the board right now "
        "(image-writing is one phase for the whole dd, so a phase that is not moving proves nothing)",
        "wait for it to finish and run the status subcommand again; do not touch any boot entry meanwhile",
        "no boot entry or staging was touched",
    ]


def _manual_disarm_lines(label, holder) -> list:
    return [
        f"the on-board flash lock is held by {holder} and did not clear in time",
        "that pid is gone, but the lock is still held, so a tool it started may still be running: "
        "check first on the board (ps -ef | grep -E 'dd|sfdisk|efibootmgr') and stop here if any is alive",
        "no boot entry or staging was touched",
        "only if nothing is running, disarm by hand as root on the board:",
        "  efibootmgr -v    (find the entry labelled "
        f"{label!r}; note BootNext, BootOrder and BootCurrent)",
        f"  efibootmgr -N    (only if BootNext names the entry labelled {label!r}; leave any other BootNext alone)",
        "  delete no boot entry: it is the firmware's own",
    ]


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
    lock_wait=EMERGENCY_LOCK_WAIT,
    run_id=None,
) -> RestoreResult:
    """Take the on-board lock, then restore. Refuses while a writer holds it.

    ``--emergency-disarm`` is the one disarm that does not depend on the run
    state, so it waits up to ``lock_wait`` seconds for a holder to finish and,
    if the lock stays held, prints the holder and the manual steps. The normal
    path refuses at once.
    """
    wait = lock_wait if emergency_disarm else 0.0
    label = profile.arm.params.get("entry_label", "") if getattr(profile.arm, "params", None) else ""
    try:
        with OnBoardLock(Path(state_dir) / LOCK_NAME, run_id=ack_run_id or "", wait_seconds=wait):
            return _restore_locked(
                ops, profile, state_dir=state_dir, staging_dir=staging_dir, ack_run_id=ack_run_id,
                emergency_disarm=emergency_disarm, remove_tree=remove_tree, out=out, run_id=run_id,
            )  # fmt: skip
    except (LockHeld, OSError) as exc:
        if isinstance(exc, LockHeld):
            why = f"another run holds the lock: {exc}"
        else:
            why = f"cannot take the on-board lock: {exc}"
        result = RestoreResult(1)
        lines = [f"refusing: {why}", "no boot entry or staging was touched"]
        if emergency_disarm and isinstance(exc, LockHeld):
            holder = _lock_holder(exc)
            steps = _manual_disarm_lines(label, holder) if _holder_gone(exc) else _live_holder_lines(holder)
            lines = [f"refusing: {why}"] + steps
        for line in lines:
            result.lines.append(line)
            out(line)
        return result


def _load_requested(state_dir, run_id) -> LoadResult:
    """The run restore acts on: the named run's own record, else whichever run ``current`` names.

    A named run whose loaded record carries a different run id is unreadable, never a stand-in.
    """
    if run_id is None:
        return load_state(state_dir)
    loaded = _load_run(state_dir, run_id)
    if loaded.status == "ok" and loaded.state.run_id != run_id:
        return LoadResult(
            "unparseable", reason=f"the record under {run_id!r} names run {loaded.state.run_id!r}", run_id=run_id
        )
    return loaded


def _restore_locked(
    ops,
    profile,
    *,
    state_dir,
    staging_dir,
    ack_run_id=None,
    emergency_disarm=False,
    remove_tree=None,
    out=print,
    run_id=None,
) -> RestoreResult:
    result = RestoreResult(0)
    expected_staging = profile.staging.dir
    if remove_tree is None:
        remove_tree = make_guarded_rmtree(expected_staging)

    def say(line):
        result.lines.append(line)
        out(line)

    to_close = {"state": None}

    def finish(code, note):
        if note:
            say(NOTE_LINE)
        st = to_close["state"]
        if code == 0 and st is not None and st.phase != "restored":
            try:
                transition(st, "restored")
            except Exception as e:  # noqa: BLE001 - an unrecorded restore must not read as success
                say(f"restore done but the run state could not be advanced: {e}; a new write stays blocked")
                code = 1
            else:
                say(
                    f"run {st.run_id} state advanced to restored: the run is closed. A new plan needs an empty "
                    "target when the profile sets require_empty (restore wipes nothing)"
                )
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

    loaded = _load_requested(state_dir, run_id)
    label = profile.arm.params.get("entry_label", "") if profile.arm.params else ""

    if emergency_disarm:
        # The lock being free does not mean nothing is running: a dd in its own session can outlive a
        # killed runner without holding the lock.
        say("before relying on this disarm, check on the board that no dd, sfdisk or efibootmgr is still "
            "running (ps -ef | grep -E 'dd|sfdisk|efibootmgr')")
        return _emergency(ops, label, ack_run_id, loaded, say, result, finish)

    if loaded.status == "unparseable":
        say(f"refusing: run state is unreadable: {loaded.reason}")
        say("no boot entry or staging was touched")
        say(
            "inspect `efibootmgr -v` by hand, or run `restore --emergency-disarm "
            "--ack-run <text>` to clear only a one-shot "
            f"setting that names the entry labelled {label!r}"
        )
        return finish(1, True)

    if loaded.status == "absent" and run_id is not None:
        say(f"refusing: no state is recorded for run {run_id}; no boot entry or staging was touched")
        say("name a run that exists, or omit --run-id to restore the current run")
        return finish(1, False)

    if loaded.status == "absent":
        say("no run state found: nothing to restore for boot entries")
        ok = clean_staging()
        return finish(0 if ok else 1, True)

    state = loaded.state
    say(f"restoring run {state.run_id}" + (" (the current run)" if run_id is None else " (named by --run-id)"))
    if state.phase not in TERMINAL and ack_run_id != state.run_id:
        say(f"refusing: run {state.run_id} is in phase {state.phase}, not finished")
        say(f"recovery: {describe_recovery(state)}")
        say(f"acknowledge it with --ack-run {state.run_id} to restore; no boot entry or staging was touched")
        return finish(1, False)
    to_close["state"] = state
    phases = [p.get("phase") for p in state.data.get("phases_done", [])]
    note = any(p in _ROLLED_PHASES for p in phases)
    say(f"run {state.run_id} phase {state.phase}: {describe_recovery(state)}")
    armed = state.data.get("armed")
    possibly_armed = state.phase == "arming"  # recorded before the first efibootmgr call
    if not isinstance(armed, dict) or not (possibly_armed or armed.get("next_armed")):
        say("no boot entry was armed by this run; no efibootmgr calls made")
        ok = clean_staging()
        return finish(0 if ok else 1, note)

    record = ArmRecord.from_dict(armed)
    if state.phase == "arming":
        # The arm step began and may have changed the boot variables further than the
        # record shows: assume BootNext is set, and find an unrecorded entry by label.
        record.next_armed = True
        if not record.entry_number:
            return _disarm_by_label(ops, record, say, result, finish, clean_staging, note)
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

        try:
            notes = Arm().disarm(ops, record)
        except ArmError as e:
            say(str(e))
            say("staging kept")
            return finish(1, note)
        for n in notes:
            result.actions.append(n)
            say(n)
        after = ops.efibootmgr_list()
    except OpsError as e:
        say(f"restore FAILED: {e}; staging kept, rerun `restore` after inspecting efibootmgr -v")
        return finish(1, note)

    still = boot_next_of(after).upper()
    if record.entry_number and still == record.entry_number.upper():
        say(f"BootNext {still} still set: DO NOT REBOOT; it did not clear")
        say("staging kept")
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


def _disarm_by_label(ops, record, say, result, finish, clean_staging, note):
    """arming with no recorded entry number: clear BootNext only if it names the one entry with the label."""
    if not record.label:
        say("refusing: the arming record has no label to match; use --emergency-disarm with an acknowledgement")
        return finish(1, True)
    try:
        for n in Arm().disarm(ops, record):
            result.actions.append(n)
            say(n)
        after = ops.efibootmgr_list()
    except OpsError as e:
        say(f"restore FAILED: {e}; staging kept, rerun `restore` after inspecting efibootmgr -v")
        return finish(1, note)
    still = boot_next_of(after).upper()
    if still and still in entries_with_label(after, record.label):
        say(f"BootNext {still} still names an entry labelled {record.label!r}; it was not cleared")
        say("staging kept")
        return finish(1, note)
    now = boot_order_of(after)
    if record.preexisting_boot_order and now != record.preexisting_boot_order:
        say(f"BootOrder {now!r} differs from recorded {record.preexisting_boot_order!r}; not changed")
        say("staging kept")
        return finish(1, note)
    if record.preexisting_boot_order:
        say(f"BootOrder {now} equals the recorded value")
    ok = clean_staging()
    return finish(0 if ok else 1, note)


def _emergency(ops, label, ack, loaded, say, result, finish):
    if not ack:
        say("refusing: --emergency-disarm needs an acknowledgement (--ack-run <text>)")
        say(f"it clears BootNext only if it names the entry labelled {label!r}; it deletes no boot entry")
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
            left = boot_next_of(ops.efibootmgr_list()).upper()
            if left == nxt:
                say(f"BootNext {left} still set: DO NOT REBOOT; it did not clear")
                return finish(1, True)
        elif not ours:
            say(f"no boot entry labelled {label!r}; BootNext left alone")
        else:
            say(f"BootNext {nxt or '(none)'} does not name the entry labelled {label!r}; nothing cleared")
    except OpsError as e:
        say(f"emergency disarm FAILED: {e}")
        return finish(1, True)
    say("BootOrder and all boot entries were not touched; staging was not touched")
    return finish(0, True)


__all__ = [
    "NOTE_LINE", "RestoreResult", "StagingRefused", "check_staging_path",
    "make_guarded_rmtree", "run_restore",
]  # fmt: skip
