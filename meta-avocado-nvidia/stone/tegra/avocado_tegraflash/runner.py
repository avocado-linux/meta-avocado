"""Process execution seam: argument lists only, never a shell."""

import os
import signal
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

CANNOT_START = 127
TIMED_OUT = 124


class Runner(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> int:
        """Run with inherited stdio; return the exit status."""
        ...

    def capture(
        self,
        argv: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        discard_stderr: bool = False,
        timeout: float | None = None,
    ) -> tuple[int, str]:
        """Run and return (exit status, standard output text).

        A command still running after `timeout` seconds is killed with its
        whole process group and reports status 124 with no output.
        """
        ...


def _wait_through_interrupt(proc: subprocess.Popen) -> int:
    """Wait for the child however long it runs; re-raise the first Ctrl-C afterwards.

    The terminal already sent SIGINT to the whole foreground group. The stdlib's
    subprocess.run would SIGKILL the child 0.25 s later and orphan whatever the
    flash tool was still tearing down, and signalling only the direct child
    would orphan its helpers just the same. Like the oracle's bash `wait`, the
    engine never signals the child: it waits, ignoring further interrupts, then
    re-raises so no later stage runs after an interrupted flash.
    """
    first: KeyboardInterrupt | None = None
    while True:
        try:
            status = proc.wait()
            break
        except KeyboardInterrupt as exc:
            first = first or exc
    if first is not None:
        raise first
    return status


class SubprocessRunner:
    def run(self, argv, *, cwd=None, env=None) -> int:
        try:
            return _wait_through_interrupt(subprocess.Popen(list(argv), cwd=cwd, env=env))
        except (FileNotFoundError, PermissionError):
            return CANNOT_START

    def capture(self, argv, *, cwd=None, env=None, discard_stderr=False, timeout=None) -> tuple[int, str]:
        # A file, not a pipe: a descendant that left the process group and kept
        # the write end open would otherwise stall the read past the timeout.
        with tempfile.TemporaryFile() as sink:
            try:
                proc = subprocess.Popen(
                    list(argv),
                    cwd=cwd,
                    env=env,
                    stdout=sink,
                    stderr=subprocess.DEVNULL if discard_stderr else None,
                    start_new_session=True,
                )
            except (FileNotFoundError, PermissionError):
                return CANNOT_START, ""
            try:
                status = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_group(proc)
                proc.wait()
                return TIMED_OUT, ""
            except BaseException:
                # Own session: the terminal's Ctrl-C no longer reaches the child.
                _kill_group(proc)
                proc.wait()
                raise
            sink.seek(0)
            return status, sink.read().decode(errors="replace")


def _kill_group(proc: subprocess.Popen) -> None:
    """Kill the child's own process group, never any other."""
    try:
        if os.getpgid(proc.pid) == proc.pid:
            os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
