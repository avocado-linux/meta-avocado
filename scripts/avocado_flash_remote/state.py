"""Durable run state machine and locks for the remote flash backend.

One JSON document per run lives at ``<state_dir>/<run_id>/state.json`` and
``<state_dir>/current`` names the active run. Every write is temp file,
flush, fsync, rename, directory fsync, so a kill at any point leaves either
the previous complete file or the new complete file on disk.

Decisions use the monotonic ``seq`` counter and the phase, never wall time;
timestamps are recorded as evidence only.

Standard library only (ships to a board running Python 3.10).
"""

from __future__ import annotations

import copy
import fcntl
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

# Name of the on-board flash lock file inside state_dir (write and restore both take it).
LOCK_NAME = "lock"

PHASES = (
    "planned",
    "table-writing",
    "table-written",
    "image-writing",
    "image-written",
    "verified",
    "arming",
    "armed",
    "complete",
    "failed",
    "restored",
)
TERMINAL = ("complete", "failed", "restored")

RECOVERY = {
    "planned": "none-recorded",
    "table-writing": "restore-then-restart",
    "table-written": "restore-then-restart",
    "image-writing": "restore-then-restart",
    "image-written": "restore-then-restart",
    "verified": "restore",
    "arming": "restore-unknown-arm",
    "armed": "restore",
}

# {run_id} is filled in by describe_recovery. `restore` only clears BootNext
# and removes staging; it deletes no boot entry (the entry is the firmware's own)
# and never rolls the partition table or any image back, so the text must not promise that.
_RECOVERY_TEXT = {
    "none-recorded": (
        "no board change has been recorded; the run never reached the first "
        "mutation, so it is safe to discard only if this run never took the "
        "on-board lock (check the lock before rerunning after acknowledging the run)"
    ),
    "restore-then-restart": (
        "the partition table may be partly or fully rewritten and an image may be partial: "
        "re-inspect the target, run restore with --ack-run {run_id} (it clears the next-boot "
        "setting if this run set it and removes the staging directory; it deletes no boot entry, "
        "does NOT roll back the partition table or any image, and wipes nothing). To start over, wipe the target's partition table "
        "by hand after re-checking that it is the profile's target device (plan refuses a disk "
        "that already has a table when the profile sets require_empty), stage the images again "
        "(restore deleted the staging directory), then plan and write. The README section "
        "'Starting over after a failed write' lists the steps"
    ),
    "restore-unknown-arm": (
        "the arm step started: the next-boot setting (BootNext) may already be set even if "
        "this record does not say so. DO NOT REBOOT. Run restore with --ack-run {run_id}: it "
        "clears BootNext if it names the entry carrying the profile's label, and removes "
        "the staging directory; it deletes no boot entry and does NOT roll back the partition table or any image"
    ),
    "restore": (
        "run restore with --ack-run {run_id} to clear the next-boot setting this run set and "
        "remove the staging directory; it deletes no boot entry and does NOT roll back the "
        "partition table or any image, and the images need no rewrite"
    ),
}


class IllegalTransition(Exception):
    pass


class RerunRefused(Exception):
    pass


class LockHeld(Exception):
    """Another process holds the lock; ``holder`` is what its lock file says (may be empty)."""

    def __init__(self, message: str, holder: str = "") -> None:
        super().__init__(message)
        self.holder = holder


def _fault(point: str) -> None:
    """Crash-injection hook; tests replace it to raise at a named point."""


def _fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write(path: Path, payload: bytes) -> None:
    _fault("before-write")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(payload)
        _fault("after-temp-write")
        fh.flush()
        os.fsync(fh.fileno())
    _fault("after-fsync")
    os.rename(str(tmp), str(path))
    _fault("after-rename")
    _fsync_dir(path.parent)


@dataclass
class RunState:
    run_dir: Path
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def phase(self) -> str:
        return self.data["phase"]

    @property
    def run_id(self) -> str:
        return self.data["run_id"]


def _dump(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()


def create_run(
    state_dir,
    *,
    run_id: str,
    profile_hash: str,
    plan_hash: str,
    board_identity: dict[str, Any],
    image_roles: list[str],
    arm: bool,
) -> RunState:
    state_dir = Path(state_dir)
    run_dir = state_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "profile_hash": profile_hash,
        "plan_hash": plan_hash,
        "board_identity": board_identity,
        "phase": "planned",
        "seq": 1,
        "arm_enabled": bool(arm),
        "image_order": list(image_roles),
        "phases_done": [{"seq": 1, "phase": "planned", "wall_time": time.time()}],
        "images": {
            r: {
                "bytes_written": 0,
                "expected_sha256": None,
                "readback_sha256": None,
                "state": "pending",
            }
            for r in image_roles
        },
        "armed": None,
        "error": None,
    }
    _atomic_write(run_dir / "state.json", _dump(data))
    _fsync_dir(state_dir)
    _atomic_write(state_dir / "current", (run_id + "\n").encode())
    return RunState(run_dir, data)


def _next_image(data: dict[str, Any]) -> str | None:
    for r in data["image_order"]:
        if data["images"][r]["state"] == "pending":
            return r
    return None


def _check_legal(data: dict[str, Any], new_phase: str, image: str | None) -> None:
    cur = data["phase"]
    if new_phase not in PHASES:
        raise IllegalTransition(f"unknown phase {new_phase!r}")
    if new_phase == "restored":
        # Reached from any phase, terminal ones included: a restore is how a
        # stuck or failed run is closed so a new plan and write can proceed.
        if cur == "restored":
            raise IllegalTransition("run is already restored")
        return
    if cur in TERMINAL:
        raise IllegalTransition(f"{cur} is terminal; cannot go to {new_phase}")
    if new_phase == "failed":
        return
    if new_phase == "table-writing":
        ok = cur == "planned"
    elif new_phase == "table-written":
        ok = cur == "table-writing"
    elif new_phase == "image-writing":
        ok = cur in ("table-written", "image-written") and image is not None and image == _next_image(data)
    elif new_phase == "image-written":
        ok = (
            cur == "image-writing"
            and image is not None
            and data["images"].get(image, {}).get("state") == "writing"
        )
    elif new_phase == "verified":
        ok = cur in ("table-written", "image-written") and _next_image(data) is None
    elif new_phase == "arming":
        # Written (and fsynced) before the first efibootmgr call; re-entering
        # arming only refreshes what is known about the entry.
        ok = (cur == "verified" and data["arm_enabled"]) or cur == "arming"
    elif new_phase == "armed":
        ok = cur in ("verified", "arming") and data["arm_enabled"]
    elif new_phase == "complete":
        ok = (cur == "verified" and not data["arm_enabled"]) or cur == "armed"
    else:  # planned
        ok = False
    if not ok:
        raise IllegalTransition(f"{cur} -> {new_phase} (image={image!r}) is not allowed")


def transition(state: RunState, new_phase: str, **fields: Any) -> RunState:
    """Validate and durably record a phase change; return the new state.

    Accepted fields: image, bytes_written, expected_sha256, readback_sha256,
    armed, error. The input state is not mutated.
    """
    image = fields.get("image")
    _check_legal(state.data, new_phase, image)
    data = copy.deepcopy(state.data)
    progress_only = new_phase == "arming" and state.data["phase"] == "arming"
    data["seq"] += 1
    data["phase"] = new_phase
    entry: dict[str, Any] = {"seq": data["seq"], "phase": new_phase, "wall_time": time.time()}
    if image is not None:
        entry["image"] = image
    if new_phase == "image-writing":
        data["images"][image]["state"] = "writing"
    elif new_phase == "image-written":
        rec = data["images"][image]
        rec["state"] = "written"
        for k in ("bytes_written", "expected_sha256", "readback_sha256", "readback_after_cache_flush"):
            if k in fields:
                rec[k] = fields[k]
    elif new_phase == "arming":
        data["armed"] = fields.get("armed")
        if "error" in fields:
            data["error"] = fields["error"]
    elif new_phase == "armed":
        data["armed"] = fields.get("armed")
    elif new_phase == "failed":
        data["error"] = fields.get("error")
    elif new_phase == "restored":
        data["restored_from"] = state.data["phase"]
    if not progress_only:
        data["phases_done"].append(entry)
    _atomic_write(state.run_dir / "state.json", _dump(data))
    return RunState(state.run_dir, data)


def _describe_failed(state: RunState) -> str:
    data = state.data
    phases = [p.get("phase") for p in data.get("phases_done", [])]
    parts = [f"the run failed ({data.get('error') or 'no error recorded'})."]
    if "table-writing" in phases:
        parts.append("The partition table was possibly rewritten (it is not rolled back).")
    else:
        parts.append("The partition table was not touched.")
    images = data.get("images") or {}
    written = [r for r in data.get("image_order", []) if images.get(r, {}).get("state") == "written"]
    partial = [r for r in data.get("image_order", []) if images.get(r, {}).get("state") == "writing"]
    pending = [r for r in data.get("image_order", []) if images.get(r, {}).get("state") == "pending"]
    if written or partial or pending:
        bits = []
        if written:
            bits.append("written and read back: " + ", ".join(written))
        if partial:
            bits.append("partial: " + ", ".join(partial))
        if pending:
            bits.append("not started: " + ", ".join(pending))
        parts.append("Images " + "; ".join(bits) + ".")
    armed = data.get("armed")
    if isinstance(armed, dict) and armed.get("next_armed"):
        parts.append(
            f"The board is armed: BootNext names boot entry {armed.get('entry_number') or '(number unknown)'}. "
            "DO NOT REBOOT until restore has cleared BootNext."
        )
    else:
        parts.append("No boot entry is recorded as armed.")
    parts.append(
        "Run restore to disarm and clean staging (no acknowledgement is needed for a finished run); "
        "restore does not roll back the table or images and wipes nothing."
    )
    if "table-writing" in phases:
        parts.append(
            "To start over, wipe the target's partition table by hand after re-checking that it is the "
            "profile's target device (plan refuses a disk that already has a table when the profile sets "
            "require_empty), stage the images again (restore deleted the staging directory), then plan and "
            "write. See the README section 'Starting over after a failed write'."
        )
    else:
        parts.append("To try again, stage the images again (restore deletes the staging directory), then plan and write.")
    return " ".join(parts)


def describe_recovery(state: RunState) -> str:
    if state.phase == "failed":
        return _describe_failed(state)
    if state.phase in TERMINAL:
        return "no recovery needed (terminal)"
    action = RECOVERY[state.phase]
    return f"{action}: " + _RECOVERY_TEXT[action].format(run_id=state.run_id)


@dataclass
class LoadResult:
    status: str  # ok | absent | unparseable
    state: RunState | None = None
    reason: str = ""
    run_id: str | None = None


_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_+][A-Za-z0-9._+-]*\Z")
_IMAGE_STATES = ("pending", "writing", "written")
_ARM_STR_KEYS = ("entry_number", "label", "preexisting_boot_order", "preexisting_next")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_armed(armed: Any) -> str | None:
    if armed is None:
        return None
    if not isinstance(armed, dict):
        return "armed is neither null nor an object"
    unknown = sorted(set(armed) - set(_ARM_STR_KEYS) - {"next_armed"})
    if unknown:
        return f"armed has unknown keys {unknown}"
    for k in _ARM_STR_KEYS:
        if armed.get(k) is not None and not isinstance(armed[k], str):
            return f"armed.{k} is not a string or null"
    if "next_armed" in armed and not isinstance(armed["next_armed"], bool):
        return "armed.next_armed is not a boolean"
    return None


def _validate(data: Any, expected_run_id: str | None = None) -> str | None:
    """Why ``data`` is not a usable run state, or None. Types and consistency, not just key presence."""
    if not isinstance(data, dict):
        return "state document is not an object"
    if data.get("schema_version") != SCHEMA_VERSION:
        return f"unsupported schema_version {data.get('schema_version')!r}"
    if data.get("phase") not in PHASES:
        return f"unknown phase {data.get('phase')!r}"
    for k in ("run_id", "seq", "arm_enabled", "image_order", "phases_done", "images"):
        if k not in data:
            return f"missing field {k!r}"
    run_id = data["run_id"]
    if not isinstance(run_id, str) or not _RUN_ID_RE.match(run_id):
        return f"bad run_id {run_id!r}"
    if expected_run_id is not None and run_id != expected_run_id:
        return f"run_id {run_id!r} does not match the run it was loaded for ({expected_run_id!r})"
    if not _is_int(data["seq"]) or data["seq"] < 1:
        return f"seq {data['seq']!r} is not a positive integer"
    if not isinstance(data["arm_enabled"], bool):
        return "arm_enabled is not a boolean"
    order = data["image_order"]
    if not isinstance(order, list) or not all(isinstance(r, str) for r in order):
        return "image_order is not a list of role names"
    done = data["phases_done"]
    if not isinstance(done, list) or not all(isinstance(p, dict) and p.get("phase") in PHASES for p in done):
        return "phases_done is not a list of known phases"
    images = data["images"]
    if not isinstance(images, dict) or not all(
        isinstance(v, dict) and v.get("state") in _IMAGE_STATES for v in images.values()
    ):
        return "images is not a mapping of image states"
    missing = [r for r in order if r not in images]
    if missing:
        return f"images has no record for ordered roles {missing}"
    return _validate_armed(data.get("armed"))


def load_state(state_dir) -> LoadResult:
    state_dir = Path(state_dir)
    ptr = state_dir / "current"
    try:
        run_id = ptr.read_text().strip()
    except FileNotFoundError:
        return LoadResult("absent")
    except (OSError, UnicodeDecodeError) as e:
        return LoadResult("unparseable", reason=f"cannot read current pointer: {e}")
    if not run_id or "/" in run_id or run_id in (".", ".."):
        return LoadResult("unparseable", reason=f"bad current pointer {run_id!r}")
    path = state_dir / run_id / "state.json"
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return LoadResult("unparseable", reason=f"{path} is missing", run_id=run_id)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return LoadResult("unparseable", reason=f"{path}: {e}", run_id=run_id)
    bad = _validate(data, run_id)
    if bad:
        return LoadResult("unparseable", reason=f"{path}: {bad}", run_id=run_id)
    return LoadResult("ok", state=RunState(path.parent, data), run_id=data["run_id"])


@dataclass
class RerunDecision:
    state: RunState | None
    recovery_only: bool = False


def check_rerun_allowed(state_dir, ack_run_id: str | None = None) -> RerunDecision:
    r = load_state(state_dir)
    if r.status == "absent":
        return RerunDecision(None)
    if r.status == "ok":
        assert r.state is not None
        if r.state.phase in TERMINAL:
            return RerunDecision(r.state)
        run_id = r.state.run_id
        what = f"phase {r.state.phase}"
        recovery = describe_recovery(r.state)
    else:
        run_id = r.run_id or "unknown"
        what = f"unparseable state ({r.reason})"
        recovery = "manual: inspect the state directory and board, then restore by hand"
    if ack_run_id is not None and ack_run_id == run_id:
        return RerunDecision(r.state, recovery_only=True)
    raise RerunRefused(
        f"run {run_id} left {what}. Permitted recovery: {recovery}. "
        f"Acknowledge by passing --ack-run {run_id} to proceed with recovery."
    )


class _FlockBase:
    label = "lock"

    def __init__(self, path, run_id: str = "", wait_seconds: float = 0.0) -> None:
        self.path = Path(path)
        self.run_id = run_id
        self.wait_seconds = wait_seconds
        self._fh = None

    def _describe(self) -> str:
        return self.label

    @staticmethod
    def _stable_record(fh) -> str:
        """The holder record, or "" when it is not the same on two reads a moment apart.

        A new holder takes the flock before it rewrites the record, so a single read can name the
        previous holder. An unstable record is reported as an unknown holder, which callers treat
        as alive.
        """
        fh.seek(0)
        first = fh.read().strip()
        time.sleep(0.05)
        fh.seek(0)
        second = fh.read().strip()
        return first if first == second else ""

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+")
        deadline = time.monotonic() + max(0.0, self.wait_seconds)
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raw = self._stable_record(fh)
                    fh.close()
                    raise LockHeld(f"{self._describe()} is held by {raw or 'unknown holder'}", raw) from None
                time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps({"pid": os.getpid(), "run_id": self.run_id}))
        fh.flush()
        self._fh = fh
        return self

    def __exit__(self, *exc) -> None:
        fh, self._fh = self._fh, None
        if fh is not None:
            try:
                fh.truncate(0)  # the last holder's pid must not outlive its hold
                fh.flush()
            except OSError:
                pass
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.close()


class OnBoardLock(_FlockBase):
    """The flash lock. ``wait_seconds`` bounds a wait for a holder; 0 refuses at once."""

    label = "on-board flash lock"

    def _describe(self) -> str:
        return f"{self.label} {self.path}"


class HostLock(_FlockBase):
    def __init__(self, path, host: str, run_id: str = "") -> None:
        super().__init__(path, run_id)
        self.host = host

    def _describe(self) -> str:
        return f"host lock for target host {self.host}"
