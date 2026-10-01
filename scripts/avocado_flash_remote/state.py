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
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

PHASES = (
    "planned",
    "table-written",
    "image-writing",
    "image-written",
    "verified",
    "armed",
    "complete",
    "failed",
)
TERMINAL = ("complete", "failed")

RECOVERY = {
    "planned": "none-needed",
    "table-written": "restore-then-restart",
    "image-writing": "restore-then-restart",
    "image-written": "restore-then-restart",
    "verified": "restore",
    "armed": "restore",
}

_RECOVERY_TEXT = {
    "none-needed": "nothing was written to the board; rerun after acknowledging the run",
    "restore-then-restart": (
        "restore the saved partition table and original data, then restart "
        "from the table phase"
    ),
    "restore": (
        "restore the saved state (partition table, boot order and next-boot "
        "entry) from the recorded values; do not rewrite images"
    ),
}


class IllegalTransition(Exception):
    pass


class RerunRefused(Exception):
    pass


class LockHeld(Exception):
    pass


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
    if cur in TERMINAL:
        raise IllegalTransition(f"{cur} is terminal; cannot go to {new_phase}")
    if new_phase == "failed":
        return
    if new_phase == "table-written":
        ok = cur == "planned"
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
    elif new_phase == "armed":
        ok = cur == "verified" and data["arm_enabled"]
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
        for k in ("bytes_written", "expected_sha256", "readback_sha256"):
            if k in fields:
                rec[k] = fields[k]
    elif new_phase == "armed":
        data["armed"] = fields.get("armed")
    elif new_phase == "failed":
        data["error"] = fields.get("error")
    data["phases_done"].append(entry)
    _atomic_write(state.run_dir / "state.json", _dump(data))
    return RunState(state.run_dir, data)


def describe_recovery(state: RunState) -> str:
    action = RECOVERY.get(state.phase)
    if action is None:
        return "no recovery needed (terminal)"
    return f"{action}: {_RECOVERY_TEXT[action]}"


@dataclass
class LoadResult:
    status: str  # ok | absent | unparseable
    state: RunState | None = None
    reason: str = ""
    run_id: str | None = None


def _validate(data: Any) -> str | None:
    if not isinstance(data, dict):
        return "state document is not an object"
    if data.get("schema_version") != SCHEMA_VERSION:
        return f"unsupported schema_version {data.get('schema_version')!r}"
    if data.get("phase") not in PHASES:
        return f"unknown phase {data.get('phase')!r}"
    for k in ("run_id", "seq", "arm_enabled", "image_order", "phases_done", "images"):
        if k not in data:
            return f"missing field {k!r}"
    return None


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
    bad = _validate(data)
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
        f"Acknowledge by passing the run id {run_id} to proceed with recovery."
    )


class _FlockBase:
    label = "lock"

    def __init__(self, path, run_id: str = "") -> None:
        self.path = Path(path)
        self.run_id = run_id
        self._fh = None

    def _describe(self) -> str:
        return self.label

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.seek(0)
            holder = fh.read().strip() or "unknown holder"
            fh.close()
            raise LockHeld(f"{self._describe()} is held by {holder}") from None
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps({"pid": os.getpid(), "run_id": self.run_id}))
        fh.flush()
        self._fh = fh
        return self

    def __exit__(self, *exc) -> None:
        fh, self._fh = self._fh, None
        if fh is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.close()


class OnBoardLock(_FlockBase):
    label = "on-board flash lock"

    def _describe(self) -> str:
        return f"{self.label} {self.path}"


class HostLock(_FlockBase):
    def __init__(self, path, host: str, run_id: str = "") -> None:
        super().__init__(path, run_id)
        self.host = host

    def _describe(self) -> str:
        return f"host lock for target host {self.host}"
