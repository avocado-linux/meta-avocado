"""The ``status`` subcommand: print the recorded phase, run id and recovery.

Strictly read-only. It takes no ops object and creates or modifies nothing,
so a host can call it after a dropped connection to reconcile with the
board's state file (the runner stays in charge of the run).

Standard library only (ships to a board running Python 3.10).
"""

from __future__ import annotations

from dataclasses import dataclass

from .state import describe_recovery, load_state


@dataclass
class StatusResult:
    exit_code: int
    phase: str | None = None
    run_id: str | None = None
    recovery: str | None = None


def run_status(state_dir, out=print) -> StatusResult:
    loaded = load_state(state_dir)
    if loaded.status == "absent":
        out("status: no run recorded")
        return StatusResult(0)
    if loaded.status == "unparseable":
        out(f"status: state unreadable run={loaded.run_id or 'unknown'}: {loaded.reason}")
        return StatusResult(1, run_id=loaded.run_id)
    state = loaded.state
    recovery = describe_recovery(state)
    out(f"status: {state.phase} run={state.run_id} recovery={recovery}")
    return StatusResult(0, state.phase, state.run_id, recovery)


__all__ = ["StatusResult", "run_status"]
