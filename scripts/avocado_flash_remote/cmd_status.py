"""The ``status`` subcommand: print the recorded phase, run id and recovery.

Strictly read-only. It takes no ops object and creates or modifies nothing,
so a host can call it after a dropped connection to reconcile with the
board's state file (the runner stays in charge of the run).

Standard library only (ships to a board running Python 3.10).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .state import LoadResult, RunState, _validate, describe_recovery, load_state


@dataclass
class StatusResult:
    exit_code: int
    phase: str | None = None
    run_id: str | None = None
    recovery: str | None = None


def _load_run(state_dir, run_id):
    """One run's own record, whatever ``current`` names now. No state.json for it is 'absent'."""
    if not isinstance(run_id, str) or not run_id or "/" in run_id or run_id in (".", ".."):
        return LoadResult("unparseable", reason=f"bad run id {run_id!r}")
    path = Path(state_dir) / run_id / "state.json"
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return LoadResult("absent", run_id=run_id)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return LoadResult("unparseable", reason=f"{path}: {e}", run_id=run_id)
    bad = _validate(data, run_id)
    if bad:
        return LoadResult("unparseable", reason=f"{path}: {bad}", run_id=run_id)
    return LoadResult("ok", state=RunState(path.parent, data), run_id=data["run_id"])


def run_status(state_dir, out=print, run_id=None) -> StatusResult:
    """Print the recorded phase. With ``run_id``, that run's own record rather than the ``current`` one.

    A host following its run asks by id: another run's create_run moves ``current``, and the host's
    run would then look unrecorded although it has finished.
    """
    loaded = load_state(state_dir) if run_id is None else _load_run(state_dir, run_id)
    if loaded.status == "absent":
        out("status: no run recorded" if run_id is None else f"status: no run recorded for run {run_id}")
        return StatusResult(0)
    if loaded.status == "unparseable":
        out(f"status: state unreadable run={loaded.run_id or 'unknown'}: {loaded.reason}")
        return StatusResult(1, run_id=loaded.run_id)
    state = loaded.state
    recovery = describe_recovery(state)
    out(f"status: {state.phase} run={state.run_id} recovery={recovery}")
    return StatusResult(0, state.phase, state.run_id, recovery)


__all__ = ["StatusResult", "run_status"]
