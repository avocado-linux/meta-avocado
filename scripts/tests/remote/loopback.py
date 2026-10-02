"""Test-only loopback board: the real host talks to the real runner.pyz (task 5.23).

``LoopbackTransport`` has the interface of ``host.SshTransport`` (it subclasses
it, so the process plumbing, the sudo wrapping and the tar streaming are the
production code). It differs in one place: ``command_line`` turns the remote
argv into a local one instead of an ``ssh`` invocation.

* The privilege wrapper is understood and stripped. ``sudo`` itself is never
  executed, and a password stream is refused.
* ``python3 <staging>/runner.pyz ...`` runs the real archive, built by
  ``bundle.build_bundle``, in its own process through a small entry script
  that swaps ``RealOps`` for ``LoopOps`` (the seam ``runner._run_sub`` already
  has: it builds ``RealOps(tool_dir)`` by module attribute). No runner code is
  edited and the runner's own detach, lock, marker and state code all run.
* Every other command (``cat``, ``tar``, ``install``, ``df``, ``test``,
  ``sha256sum``, ``sh -c``) is the real local tool. An absolute path argument
  must lie under the board root (or be ``/proc``), so no block device, and
  nothing outside the temp directory, can be named.

``loopback_ops.LoopOps`` is a ``RecordingOps`` that answers the fixture-none board's reads
and fails on anything it was not taught (never a silent default). It can hold a
write inside its ``dd`` so a test can act while a runner is mid-write.

No socket is opened (the suite-wide guard still applies), no block device is
touched and no ``sudo`` is run.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import sys
import time

from avocado_flash_remote import cli, host
from avocado_flash_remote.host import HostError, SshTransport
from loopback_ops import DEVICE, HOLD_FILE, IN_DD_FILE, loopback_profile

HERE = pathlib.Path(__file__).resolve().parent


def wait_until(pred, timeout=15.0, step=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return pred()


def is_zombie(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] == "Z"
    except (FileNotFoundError, ProcessLookupError):
        return False


ENTRY_SOURCE = """\
import sys
archive, *argv = sys.argv[1:]
sys.path.insert(0, archive)
sys.path.insert(0, {tests!r})
import loopback_ops
from avocado_flash_remote import runner
runner.RealOps = lambda tool_dir: loopback_ops.LoopOps({root!r})
import os
if os.path.exists(os.path.join({root!r}, "fail-accepted")):
    _atomic_marker = runner._atomic_marker

    def _failing_marker(final, text):
        if final.endswith("/accepted"):
            raise OSError(28, "No space left on device")
        return _atomic_marker(final, text)

    runner._atomic_marker = _failing_marker
sys.exit(runner.main(argv, archive=archive))
"""


# ------------------------------------------------------------------- transport


class LoopbackTransport(SshTransport):
    """Same interface as SshTransport; commands run locally, confined to the board root."""

    def __init__(self, root):
        super().__init__("op@loopback.invalid")
        self.root = pathlib.Path(root)
        self.entry = self.root / "entry.py"
        self.entry.write_text(ENTRY_SOURCE.format(tests=str(HERE), root=str(self.root)))
        self.calls: list = []
        self.requests: list = []

    def _confine(self, argv):
        root = str(self.root)
        for arg in argv:
            if arg.startswith("/") and not (arg == root or arg.startswith(root + "/") or arg.startswith("/proc/")):
                raise HostError(f"loopback: {arg!r} is outside the loopback root")

    def command_line(self, remote_argv):
        argv = list(remote_argv)
        if argv[:1] == ["sudo"]:
            if argv[:2] != ["sudo", "-n"]:
                raise HostError("loopback: password sudo is not supported")
            argv = argv[2:]
            if argv == ["true"]:
                argv = ["true"]  # the sudo -n probe: the wrapper is understood, never executed
        self._confine(argv)
        self.calls.append(list(argv))
        if argv[:1] == ["python3"]:
            rest = argv[1:]
            if rest and rest[0].endswith(".pyz"):
                return [sys.executable, str(self.entry), *rest]
            return [sys.executable, *rest]
        return argv

    def run(self, argv_remote, stdin=None, *, sudo=False, timeout=host.DEFAULT_TIMEOUT):
        argv = list(argv_remote)
        if argv[:2] == ["sh", "-c"] and "cat >" in argv[2] and isinstance(stdin, (bytes, bytearray)):
            self.requests.append((argv[-1], json.loads(bytes(stdin))))
        return super().run(argv, stdin, sudo=sudo, timeout=timeout)


# ----------------------------------------------------------------------- board

IMAGE_NAMES = ("boot.img", "esp.img", "data.img")


class LoopbackBoard:
    def __init__(self, tmp_path):
        self.tmp = pathlib.Path(tmp_path)
        self.root = self.tmp / "board"
        self.root.mkdir()
        self.stage = self.root / "stage"
        self.state = self.root / "state"
        self.evidence = self.tmp / "ev"
        self.images = self.tmp / "images"
        self.images.mkdir()
        lines = []
        for name in IMAGE_NAMES:
            data = (name.encode() + b"-payload") * 50
            (self.images / name).write_bytes(data)
            lines.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
        (self.images / "MANIFEST.hashes").write_text("".join(lines))
        prof = loopback_profile(self.stage, self.state)
        self.ext = self.tmp / "ext"
        self.ext.mkdir()
        (self.ext / "fixture-none.json").write_text(json.dumps(prof, indent=2))
        self.transport = LoopbackTransport(self.root)

    # -- driving the host ----------------------------------------------------
    def cli(self, sub, *extra, evidence=None, sleep=None, wait_seconds=None):
        out: list = []
        argv = [
            sub, "--board", "fixture-none", "--images", str(self.images),
            "--extension-dir", str(self.ext),
            "--evidence-dir", str(evidence or self.evidence), "--host", "op@loopback.invalid", *extra,
        ]  # fmt: skip
        err = _capture_stderr()
        with err:
            rc = cli.main(
                argv,
                transport_factory=lambda host_arg, opts, batch: self.transport,
                out=out.append,
                sleep=sleep or (lambda s: None),
                confirm=lambda prompt: DEVICE,
                poll_interval=1.0,
            )
        return rc, "\n".join(map(str, out)), err.text

    def plan_run_id(self):
        return sorted(p.name for p in self.evidence.iterdir() if p.is_dir())[0]

    def copy_plan(self, run_id, other_evidence):
        other_evidence = pathlib.Path(other_evidence)
        other_evidence.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.evidence / run_id, other_evidence / run_id)

    # -- the board's records ---------------------------------------------------
    def run_dir(self, run_id):
        return self.state / run_id / "records"

    def marker(self, run_id, name):
        return (self.run_dir(run_id) / name).read_text()

    def snapshot(self, run_id):
        """Bytes of every record file the runner keeps for this run (None when absent)."""
        names = ("accepted", "outcome", "MANIFEST.json", "plan.json", "write.json")
        out = {}
        for n in names:
            p = self.run_dir(run_id) / n
            out[n] = p.read_bytes() if p.exists() else None
        return out

    def last_request(self, sub):
        for _path, body in reversed(self.transport.requests):
            if _path.endswith(f"request-{sub}.json") or f"request-{sub}" in _path:
                return body
        raise AssertionError(f"no {sub} request was sent")

    def fail_accepted_writes(self):
        """From now on the runner's attempt to write its accepted marker fails (a full disk)."""
        (self.root / "fail-accepted").write_text("1")

    # -- holding a write inside dd -------------------------------------------
    def hold(self):
        (self.root / HOLD_FILE).write_text("hold")

    def release(self):
        try:
            (self.root / HOLD_FILE).unlink()
        except FileNotFoundError:
            pass

    def wait_in_dd(self, timeout=30.0):
        return wait_until(lambda: (self.root / IN_DD_FILE).exists(), timeout=timeout)

    def _is_ours(self, pid):
        """True only for a process whose command line names this board's entry script."""
        try:
            return str(self.transport.entry).encode() in pathlib.Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError:
            return False

    def reap(self):
        """Leave no runner behind: SIGKILL any pid an accepted marker names that is still ours."""
        for acc in self.state.glob("*/records/accepted"):
            try:
                pid = int(acc.read_text().split("\n")[0])
            except (OSError, ValueError):
                continue
            if not self._is_ours(pid):
                continue
            if os.path.exists(f"/proc/{pid}") and not is_zombie(pid):
                try:
                    os.kill(pid, 9)  # only a runner this test started
                except ProcessLookupError:
                    pass


class _capture_stderr:
    def __enter__(self):
        import io

        self._buf = io.StringIO()
        self._old = sys.stderr
        sys.stderr = self._buf
        return self

    def __exit__(self, *exc):
        sys.stderr = self._old

    @property
    def text(self):
        return self._buf.getvalue()


__all__ = ["LoopbackBoard", "LoopbackTransport"]
