"""The ``write`` subcommand core: the only code path that mutates the board.

Every step before the first mutation is read-only and goes through a
``ReadOnlyOps`` wrapper, so a slip there raises ``MutationRefused`` instead
of writing. The first mutating call (the ``sfdisk`` table write) happens only
after, in order:

1. a plan record exists and its image hashes, profile hash, board identity,
   device and table hash match what is on the board now;
2. no unfinished run is recorded in the state directory;
3. the on-board lock is held;
4. the read-only check passes and the plan's root-backing / target-device
   tests pass again;
5. the operator retyped the target device (or assumed yes).

Then the state machine runs: table-writing, table-written, one image-writing / image-written
pair per image (re-verify the staged file, ``dd`` it with the kit's vector,
read the partition back and compare sha256), verified, guard, arming, armed, complete.
Every transition is durable before the next step; ``arming`` is recorded
before the first ``efibootmgr`` call and refreshed as the entry number and
BootNext become known, so a crash mid-arm leaves a state that says the board
may be armed. A read-back mismatch, a guard refusal or any exception before
the arm step records ``failed`` and never arms. A failure inside the arm step
that may have changed the boot variables leaves ``arming`` with an error note
(armed state unknown), so restore and status treat it as possibly armed.

Detaching the runner from the SSH session is the runner entry's job; this
module is the pure write logic. When in doubt it refuses and says why.

Standard library only (ships to a board running Python 3.10).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import arm as armmod
from . import cmd_plan, evidence, images, layout
from .cmd_check import DEFAULT_EFIVARS_DIR, run_check
from .ops import DD_WRITE_TIMEOUT, OpFailed, Ops, ReadOnlyOps
from .state import (
    LOCK_NAME,
    LockHeld,
    OnBoardLock,
    RerunRefused,
    check_rerun_allowed,
    create_run,
    describe_recovery,
    load_state,
    transition,
)

RECORD_NAME = "write.json"
READBACK_BS = "4M"

_DUMP_PART_RE = re.compile(r"^(\S+)\s*:\s*start=\s*(\d+),\s*size=\s*(\d+)")


class _Refusal(Exception):
    """Raised before the first mutation; nothing was written."""


class _Failed(Exception):
    """A step after the first mutation failed; becomes the ``failed`` phase."""


@dataclass
class WriteResult:
    exit_code: int
    final_phase: str | None
    run_id: str | None
    lines: list = field(default_factory=list)


# ------------------------------------------------------------ pre-mutation


def _scan_images(profile, staging_dir: str, scanner: Callable) -> dict:
    """One scanner pass per staged file; returns file name -> ScanResult."""
    scans: dict = {}
    for role, img in profile.images.items():
        if img.file in scans:
            continue
        try:
            scans[img.file] = scanner(f"{staging_dir}/{img.file}")
        except OSError as exc:
            raise _Refusal(f"staged image {role} {img.file} cannot be read in {staging_dir}: {exc}") from None
    return scans


def _authorise(plan: dict, profile, profile_hash: str, ro: Ops, scans: dict, sfdisk_text: str) -> None:
    for key in ("run_id", "profile_hash", "board_identity", "image_hashes", "device", "table_hash"):
        if key not in plan:
            raise _Refusal(f"plan record is malformed: missing {key!r}; run plan again")
    current_images = {role: scans[img.file].sha256 for role, img in profile.images.items()}
    planned_images = plan["image_hashes"]
    if not isinstance(planned_images, dict):
        raise _Refusal("plan record is malformed: image_hashes is not an object; run plan again")
    roles = sorted(set(planned_images) | set(current_images))
    changed = [r for r in roles if planned_images.get(r) != current_images.get(r)]
    if changed:
        raise _Refusal(
            "staged image changed since the plan (hash mismatch for role(s): "
            + ", ".join(changed)
            + "); run plan again"
        )
    if plan["profile_hash"] != profile_hash:
        raise _Refusal(
            f"profile changed since the plan (plan {plan['profile_hash']}, now {profile_hash}); run plan again"
        )
    if plan["device"] != profile.target.device:
        raise _Refusal(f"plan was made for {plan['device']}, the profile targets {profile.target.device}")
    _, serial = cmd_plan._resolve_identity(ro, profile)
    board = {
        "machine_id": cmd_plan._read_text(ro, "/etc/machine-id") or cmd_plan.UNAVAILABLE,
        "device_serial": serial,
    }
    if plan["board_identity"] != board:
        raise _Refusal(
            f"board identity changed since the plan (plan {plan['board_identity']}, now {board}); "
            "this is not the board that was planned"
        )
    if plan["table_hash"] != hashlib.sha256(sfdisk_text.encode()).hexdigest():
        raise _Refusal("partition table input differs from the plan's table hash; run plan again")
    current = {
        "image_hashes": current_images,
        "profile_hash": profile_hash,
        "board_identity": board,
        "run_id": plan["run_id"],
    }
    if not evidence.authorise(plan, current):
        raise _Refusal("plan record does not authorise this write")


def _reread_target_tests(ro: Ops, profile, staging_dir: str) -> None:
    """The plan's own device / root-backing tests, run again immediately before mutation."""
    cmd_plan._check_device(profile.target.device)
    cmd_plan._check_sectors(ro, profile)
    cmd_plan._check_not_in_use(ro, profile, staging_dir)
    if profile.target.require_empty:
        cmd_plan._check_empty(ro, profile)


class _ArmWatch:
    """Pass-through to the ops that notes whether a boot-variable mutation was attempted."""

    def __init__(self, ops):
        self._ops = ops
        self.attempted = False

    def __getattr__(self, name):
        attr = getattr(self._ops, name)
        if name in ("efibootmgr_create", "efibootmgr_next"):

            def watched(*a, **kw):
                self.attempted = True
                return attr(*a, **kw)

            return watched
        return attr


class _TrackedRecord(armmod.ArmRecord):
    """ArmRecord that reports each change of what is known about the boot entry.

    Arm.arm fills entry_number and next_armed in place as it goes; this hook
    makes each of those durable immediately so the state names what exists.
    """

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
        hook = self.__dict__.get("_hook")
        if hook is not None and name in ("entry_number", "next_armed"):
            hook(self)


def _prior_state_gate(state_dir, plan_run_id: str, ack_run_id) -> None:
    try:
        decision = check_rerun_allowed(state_dir, ack_run_id)
    except RerunRefused as exc:
        raise _Refusal(f"a previous run is not finished: {exc}") from None
    if decision.recovery_only:
        raise _Refusal(
            f"run {ack_run_id} is acknowledged for recovery only; run restore, wipe the target's partition "
            "table by hand if it has one (plan refuses it when the profile sets require_empty), stage the "
            "images again, then plan and write"
        )
    prior = load_state(state_dir)
    if prior.status == "ok" and prior.state is not None and prior.state.run_id == plan_run_id:
        raise _Refusal(f"plan {plan_run_id} was already used by a finished run; run plan again")
    # Whatever `current` names, a run id that already has a state record is never
    # written again: create_run would overwrite that record.
    if (Path(state_dir) / plan_run_id / "state.json").exists():
        raise _Refusal(
            f"run {plan_run_id} already has a state record under {state_dir}; "
            "it is never overwritten: run plan again for a new run id"
        )


# ---------------------------------------------------------------- mutation


def _verify_table(ops: Ops, profile, dev: str) -> None:
    """The kit's post-sfdisk checks: table present, every partition as planned, sizes live."""
    res = ops.sfdisk_dump(dev, check=False)
    if res.rc != 0 or "label:" not in res.text:
        raise _Failed(f"no partition table found on {dev} after sfdisk")
    live = {}
    for ln in res.text.splitlines():
        m = _DUMP_PART_RE.match(ln.strip())
        if m:
            live[m.group(1)] = (int(m.group(2)), int(m.group(3)))
    params = profile.layout.params
    sector = params.get("sector_size", 512)
    ordered = sorted(params["table"], key=lambda p: (p["start"], p["number"]))
    for p in ordered:
        node = layout.partition_node(dev, p["number"])
        if node not in live:
            raise _Failed(f"partition {p['number']} ({node}) missing after sfdisk")
        if live[node] != (p["start"], p["size"]):
            raise _Failed(
                f"partition {p['number']} differs from the plan after sfdisk "
                f"(start={live[node][0]} size={live[node][1]})"
            )
    for p in ordered:
        node = layout.partition_node(dev, p["number"])
        want = p["size"] * sector
        got = ops.blockdev_getsize64(node)
        if got != want:
            raise _Failed(f"{node} is {got} bytes, expected {want}")


def _write_images(ops, profile, plan, st, scans, staging_dir, reverifier, say, advance):
    dev = profile.target.device
    for role, img in profile.images.items():
        node = layout.partition_node(dev, img.partition)
        src = f"{staging_dir}/{img.file}"
        scan = scans[img.file]
        expected = plan["image_hashes"][role]
        st = advance(st, "image-writing", image=role)
        say(f"writing {img.file} -> {node} ({role})")
        try:
            reverifier(src, scan)
        except images.ImageChanged as exc:
            raise _Failed(f"staged image {role} changed after the plan: {exc}") from None
        ops.dd_write(src, node)
        live = ops.dd_sha256(node, READBACK_BS, scan.size, timeout=DD_WRITE_TIMEOUT)
        if live != expected:
            raise _Failed(
                f"readback of {node} ({role}) does not match the planned checksum "
                f"(expected {expected}, read {live}); nothing was armed"
            )
        st = advance(
            st, "image-written", image=role, bytes_written=scan.size, expected_sha256=expected, readback_sha256=live
        )
    return st


def _esp_is_vfat(ops, profile) -> None:
    esp = profile.images.get("esp")
    if profile.arm.strategy == "none" or esp is None:
        return
    node = layout.partition_node(profile.target.device, esp.partition)
    res = ops.blkid(node, check=False)
    if res.text.strip() != "vfat":
        raise _Failed(f"{node} does not read back as a FAT filesystem")


# --------------------------------------------------------------------- run


def run_write(
    ops: Ops,
    profile,
    profile_hash: str,
    *,
    staging_dir: str,
    state_dir,
    run_dir: str,
    plan_loader: Callable,
    record_writer: Callable | None = None,
    confirm: Callable | None = None,
    assume_yes: bool = False,
    expected_boot_order: str | None = None,
    efivars_dir: str = DEFAULT_EFIVARS_DIR,
    ack_run_id: str | None = None,
    out: Callable = print,
    scanner: Callable = images.scan,
    reverifier: Callable = images.reverify,
    file_reader: Callable | None = None,
) -> WriteResult:
    """Write the planned images to the target. See the module docstring."""
    result = WriteResult(1, None, None)
    writer = record_writer or evidence.write_record
    dev = profile.target.device

    def say(line):
        result.lines.append(line)
        out(line)

    def refuse(text):
        say(f"write refused: {text}")
        say("nothing was written to the board")
        return result

    ro = ReadOnlyOps(ops)
    state_dir = Path(state_dir)

    # ---- 1-2: plan record and authorisation (read-only)
    try:
        try:
            plan = plan_loader()
        except (OSError, ValueError):
            plan = None
        if not isinstance(plan, dict) or not plan:
            raise _Refusal("no plan record: run plan first")
        result.run_id = plan.get("run_id") if isinstance(plan.get("run_id"), str) else None
        if not result.run_id:
            raise _Refusal("plan record is malformed: no run_id; run plan again")
        scans = _scan_images(profile, staging_dir, scanner)
        try:
            layout.check_fits(profile.layout.params, profile.target.sectors)
            sfdisk_text = layout.sfdisk_input(profile.layout.params, dev)
        except layout.LayoutError as exc:
            raise _Refusal(f"layout does not fit the target: {exc}") from exc
        _authorise(plan, profile, profile_hash, ro, scans, sfdisk_text)
        try:
            armmod.get_guard(profile.guard.strategy).check_staged(profile, staging_dir, file_reader)
        except armmod.GuardError as exc:
            raise _Refusal(str(exc)) from exc
        # ---- 3: prior state
        _prior_state_gate(state_dir, result.run_id, ack_run_id)
    except _Refusal as exc:
        return refuse(exc)
    except cmd_plan._Refusal as exc:
        return refuse(exc)
    except Exception as exc:  # noqa: BLE001 - any doubt before mutation is a refusal
        return refuse(f"pre-check could not complete ({type(exc).__name__}: {exc})")

    # ---- 4: locks
    try:
        with OnBoardLock(state_dir / LOCK_NAME, run_id=result.run_id):
            return _locked(
                result, say, refuse, ops, ro, profile, profile_hash, plan, scans, sfdisk_text,
                staging_dir, state_dir, run_dir, writer, confirm, assume_yes, expected_boot_order,
                efivars_dir, ack_run_id, reverifier,
            )  # fmt: skip
    except LockHeld as exc:
        return refuse(f"another run holds the lock: {exc}")
    except OSError as exc:
        return refuse(f"cannot take the on-board lock: {exc}")


def _locked(
    result, say, refuse, ops, ro, profile, profile_hash, plan, scans, sfdisk_text,
    staging_dir, state_dir, run_dir, writer, confirm, assume_yes, expected_boot_order,
    efivars_dir, ack_run_id, reverifier,
):  # fmt: skip
    dev = profile.target.device
    run_id = result.run_id
    arm_impl = armmod.get_arm(profile.arm.strategy)
    arm_enabled = profile.arm.strategy != "none"

    # ---- 5-7: re-check, re-test, confirm (all still read-only)
    try:
        # Re-read the state under the lock: another run may have finished in between.
        _prior_state_gate(state_dir, run_id, ack_run_id)
        planned_arm = plan.get("arm") if isinstance(plan.get("arm"), dict) else {}
        order = expected_boot_order
        if order is None and arm_enabled:
            order = planned_arm.get("preexisting_boot_order") or None
        check_lines: list = []
        chk = run_check(
            ro, profile, staging_dir=staging_dir, efivars_dir=efivars_dir,
            expected_boot_order=order, out=check_lines.append,
        )  # fmt: skip
        if chk.exit_code != 0:
            for ln in check_lines:
                say(ln)
            raise _Refusal(f"pre-flight check did not pass (exit {chk.exit_code}, {chk.examined}/{chk.total} examined)")
        _reread_target_tests(ro, profile, staging_dir)
        try:
            record = arm_impl.prepare(ro, profile)
        except armmod.ArmError as exc:
            raise _Refusal(f"arm pre-flight refused: {exc}") from exc
        if arm_enabled and record.preexisting_boot_order != planned_arm.get("preexisting_boot_order"):
            raise _Refusal(
                f"BootOrder changed since the plan (plan {planned_arm.get('preexisting_boot_order')!r}, "
                f"now {record.preexisting_boot_order!r}); run plan again"
            )
        say(f"about to write {len(profile.images)} image(s) to {dev}; this destroys the eMMC contents")
        for role, img in profile.images.items():
            say(f"  {img.file} -> {layout.partition_node(dev, img.partition)} ({role})")
        if not assume_yes:
            if confirm is None:
                raise _Refusal("no confirmation available and assume-yes not given")
            typed = confirm(dev)
            if not isinstance(typed, str) or typed.rstrip("\r\n") != dev:
                raise _Refusal(f"confirmation did not match {dev}")
    except (_Refusal, cmd_plan._Refusal) as exc:
        return refuse(exc)
    except Exception as exc:  # noqa: BLE001
        return refuse(f"pre-check could not complete ({type(exc).__name__}: {exc})")

    # ---- 8: from here on every step is recorded; first mutation follows
    plan_hash = hashlib.sha256((json.dumps(plan, indent=2, sort_keys=True) + "\n").encode()).hexdigest()
    try:
        st = create_run(
            state_dir, run_id=run_id, profile_hash=profile_hash, plan_hash=plan_hash,
            board_identity=plan["board_identity"], image_roles=list(profile.images), arm=arm_enabled,
        )  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - nothing mutated yet
        return refuse(f"cannot create the run state: {exc}")

    box = {"st": st}

    def advance(state, phase, **fields):
        new = transition(state, phase, **fields)
        box["st"] = new
        return new

    try:
        node_by_name = {
            p["name"]: layout.partition_node(dev, p["number"]) for p in profile.layout.params["table"]
        }
        say(f"run {run_id}: writing the partition table on {dev}")
        st = advance(st, "table-writing")  # durable before the first mutation
        ops.sfdisk_write(dev, sfdisk_text)
        st = advance(st, "table-written")
        try:
            ops.udevadm_settle()
        except OpFailed as exc:
            say(f"note: udevadm settle failed ({exc}); continuing, the table is verified next")
        _verify_table(ops, profile, dev)
        st = _write_images(ops, profile, plan, st, scans, staging_dir, reverifier, say, advance)
        _esp_is_vfat(ops, profile)
        say("readback checksums OK")
        st = advance(st, "verified")
        try:
            armmod.get_guard(profile.guard.strategy).check(ops, profile, node_by_name)
        except armmod.GuardError as exc:
            raise _Failed(f"guard refused to arm: {exc}") from None
        if arm_enabled:
            tracked = _TrackedRecord(**record.to_dict())
            # Write-ahead: durable before the first efibootmgr mutation.
            st = advance(st, "arming", armed=tracked.to_dict())

            def note_progress(rec):
                advance(box["st"], "arming", armed=rec.to_dict())

            object.__setattr__(tracked, "_hook", note_progress)
            watch = _ArmWatch(ops)
            try:
                record = arm_impl.arm(watch, profile, tracked)
            except Exception as exc:  # noqa: BLE001
                box["arm_attempted"] = watch.attempted
                raise _Failed(
                    f"{exc} [entry {tracked.entry_number or 'unknown'} recorded for restore]"
                ) from None
            except BaseException:
                box["arm_attempted"] = watch.attempted
                raise
            st = advance(box["st"], "armed", armed=record.to_dict())
        st = advance(st, "complete")
    except BaseException as exc:  # noqa: BLE001 - record failed, then let non-Exception propagate
        text = str(exc) if isinstance(exc, (_Failed, Exception)) and str(exc) else type(exc).__name__
        # A failure inside the arm step that may have touched the boot
        # variables stays in `arming`: the board may be armed and the state
        # must say so. Before any efibootmgr mutation it is an ordinary failure.
        maybe_armed = box["st"].phase == "arming" and box.get("arm_attempted", True)
        try:
            if maybe_armed:
                box["st"] = transition(box["st"], "arming", armed=box["st"].data.get("armed"), error=text)
            else:
                box["st"] = transition(box["st"], "failed", error=text)
        except Exception:  # noqa: BLE001 - the last durable phase stands
            pass
        result.final_phase = box["st"].phase
        say(f"write FAILED in phase {box['st'].phase}: {text}")
        say(f"recovery: {describe_recovery(box['st'])}")
        armed_rec = box["st"].data.get("armed") or {}
        if armed_rec.get("next_armed"):
            say(f"the board WAS armed: DO NOT REBOOT; run restore --ack-run {run_id}")
        elif box["st"].phase == "arming":
            known = armed_rec.get("entry_number")
            say(
                f"the arm state is UNKNOWN (boot entry {known or 'number not recorded'}; BootNext may be set): "
                f"DO NOT REBOOT; run restore --ack-run {run_id}"
            )
        else:
            say("the board was not armed")
        _write_evidence(writer, run_dir, box["st"], say)
        if not isinstance(exc, Exception):
            raise
        return result

    result.exit_code = 0
    result.final_phase = st.phase
    if arm_enabled:
        say(f"BootNext: {record.entry_number} armed, BootOrder unchanged: {record.preexisting_boot_order}")
        say("next: systemctl reboot. A plain power cycle afterwards returns to the previous boot device. Undo with: restore")
    else:
        say("images written and verified; nothing was armed")
    _write_evidence(writer, run_dir, st, say)
    return result


def _write_evidence(writer, run_dir, st, say) -> None:
    """Evidence only: a failure to write it never changes the outcome."""
    data = {
        "run_id": st.run_id,
        "phase": st.phase,
        "error": st.data.get("error"),
        "images": st.data.get("images"),
        "armed": st.data.get("armed"),
        "transition_log": st.data.get("phases_done"),
    }
    try:
        writer(run_dir, RECORD_NAME, data)
    except OSError as exc:
        say(f"note: cannot write {RECORD_NAME} into {run_dir}: {exc}")


__all__ = ["WriteResult", "run_write"]
