"""The ``restore`` subcommand: disarm and clean up, never a rollback.

Scope: remove the boot entry this tool created (matched by its recorded
number AND label) and the one-shot BootNext, verify the boot order still
equals the value recorded before any mutation, then remove the staging
directory. Partition table and image changes are NOT rolled back, and the
output says so. After a reboot into the test entry only staging is cleaned.

It takes the on-board flash lock first and refuses while another holder is
live, so it can never run against a write in progress. A run in a non-terminal
phase needs ``--ack-run RUN_ID`` naming that run. After a successful restore the
run's state is advanced to the terminal ``restored`` so a new plan and write
are accepted by the state gate (plan itself still refuses a target that has a
partition table when the profile sets ``require_empty``: restore wipes nothing).

With missing or unparseable state it refuses; ``--emergency-disarm`` (plus an
acknowledgement) removes only entries carrying the profile's arm label and a
BootNext that points at one of them.

Standard library only (ships to a board running Python 3.10).
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .arm import Arm, ArmRecord, _field, boot_next_of, boot_order_of, entries_with_label
from .ops import OpsError
from .state import LOCK_NAME, TERMINAL, LockHeld, OnBoardLock, describe_recovery, load_state, transition

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


def _bootable(live, ours) -> dict:
    """Labelled entries that the firmware may boot: in BootOrder, or the one just booted."""
    order = {e.strip().upper() for e in boot_order_of(live).split(",") if e.strip()}
    current = _field(live, "BootCurrent").upper()
    why = {}
    for num in ours:
        if num in order:
            why[num] = "is in BootOrder"
        elif current and num == current:
            why[num] = "is BootCurrent (the board booted it)"
    return why


def _refuse_bootable(say, bootable) -> None:
    for num, why in sorted(bootable.items()):
        say(f"refusing: boot entry {num} carries this tool's label but {why}")
    say("no boot entry was deleted; inspect `efibootmgr -v` and remove the entry by hand if it is really ours")


def _entry_present(text, number) -> bool:
    return re.search(rf"^Boot{re.escape(number)}\b", text, re.IGNORECASE | re.MULTILINE) is not None


def _lock_holder(exc) -> str:
    raw = getattr(exc, "holder", "") or ""
    try:
        data = json.loads(raw)
        return f"pid {data.get('pid')} (run {data.get('run_id') or 'none'})"
    except (ValueError, AttributeError, TypeError):
        return raw or "an unknown holder"


def _manual_disarm_lines(label, holder) -> list:
    return [
        f"the on-board flash lock is held by {holder} and did not clear in time",
        "STOP if that process is alive (ps -p <pid>) and the write's phase is still moving "
        "(run the status subcommand twice): it is a healthy write still working, so wait for it and do nothing below",
        "no boot entry or staging was touched",
        "only if the holder is gone, or its phase has stopped moving, disarm by hand as root on the board:",
        "  efibootmgr -v    (find the entries labelled "
        f"{label!r}; note BootNext, BootOrder and BootCurrent)",
        f"  efibootmgr -N    (only if BootNext names an entry labelled {label!r}; leave any other BootNext alone)",
        "  efibootmgr -B -b XXXX    (delete one labelled entry that is not in BootOrder and is not BootCurrent)",
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
) -> RestoreResult:
    """Take the on-board lock, then restore. Refuses while a writer holds it.

    ``--emergency-disarm`` is the one disarm that does not depend on the run
    state, so it waits up to ``lock_wait`` seconds for a holder to finish and,
    if the lock stays held, prints the holder and the manual steps. The normal
    path refuses at once.
    """
    wait = lock_wait if emergency_disarm else 0.0
    label = profile.arm.params.get("label", "") if getattr(profile.arm, "params", None) else ""
    try:
        with OnBoardLock(Path(state_dir) / LOCK_NAME, run_id=ack_run_id or "", wait_seconds=wait):
            return _restore_locked(
                ops, profile, state_dir=state_dir, staging_dir=staging_dir, ack_run_id=ack_run_id,
                emergency_disarm=emergency_disarm, remove_tree=remove_tree, out=out,
            )  # fmt: skip
    except (LockHeld, OSError) as exc:
        if isinstance(exc, LockHeld):
            why = f"another run holds the lock: {exc}"
        else:
            why = f"cannot take the on-board lock: {exc}"
        result = RestoreResult(1)
        lines = [f"refusing: {why}", "no boot entry or staging was touched"]
        if emergency_disarm and isinstance(exc, LockHeld):
            lines = [f"refusing: {why}"] + _manual_disarm_lines(label, _lock_holder(exc))
        for line in lines:
            result.lines.append(line)
            out(line)
        return result


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

    loaded = load_state(state_dir)
    label = profile.arm.params.get("label", "") if profile.arm.params else ""

    if emergency_disarm:
        return _emergency(ops, label, ack_run_id, loaded, say, result, finish)

    if loaded.status == "unparseable":
        say(f"refusing: run state is unreadable: {loaded.reason}")
        say("no boot entry or staging was touched")
        say(
            "inspect `efibootmgr -v` by hand, or run `restore --emergency-disarm "
            "--ack-run <text>` to remove only entries labelled "
            f"{label!r} and the one-shot setting"
        )
        return finish(1, True)

    if loaded.status == "absent":
        say("no run state found: nothing to restore for boot entries")
        ok = clean_staging()
        return finish(0 if ok else 1, True)

    state = loaded.state
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
    if not isinstance(armed, dict) or not (possibly_armed or armed.get("entry_number") or armed.get("next_armed")):
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


def _disarm_by_label(ops, record, say, result, finish, clean_staging, note):
    """arming with no recorded entry number: remove only entries with the recorded label."""
    label = record.label
    if not label:
        say("refusing: the arming record has no label to match; use --emergency-disarm with an acknowledgement")
        return finish(1, True)
    try:
        live = ops.efibootmgr_list()
        ours = entries_with_label(live, label)
        bootable = _bootable(live, ours)
        if bootable:
            _refuse_bootable(say, bootable)
            say("staging kept")
            return finish(1, note)
        nxt = boot_next_of(live).upper()
        if nxt and nxt in ours:
            ops.efibootmgr_delete_next()
            result.actions.append(f"cleared BootNext {nxt}")
            say(f"cleared BootNext {nxt}")
        for num in ours:
            ops.efibootmgr_delete(num)
            result.actions.append(f"deleted boot entry {num}")
            say(f"deleted boot entry {num}")
        if not ours:
            say(f"no boot entry labelled {label!r} found; nothing removed")
        after = ops.efibootmgr_list()
    except OpsError as e:
        say(f"restore FAILED: {e}; staging kept, rerun `restore` after inspecting efibootmgr -v")
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
        say(f"it removes only boot entries labelled {label!r} and BootNext if it points at one")
        return finish(1, True)
    if not label:
        say("refusing: the profile has no arm label to match")
        return finish(1, True)
    say(f"emergency disarm acknowledged ({ack}); run state: {loaded.status}")
    try:
        live = ops.efibootmgr_list()
        ours = entries_with_label(live, label)
        bootable = _bootable(live, ours)
        if bootable:
            _refuse_bootable(say, bootable)
            return finish(1, True)
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
