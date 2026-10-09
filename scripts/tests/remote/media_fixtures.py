"""Fixtures for the existing-media regression baseline.

The script under test is `scripts/avocado-flash`: a hyphenated name with no
.py suffix, so it cannot be imported by name. `load_avocado_flash` loads it by
path with SourceFileLoader instead.

Two ways of driving it, chosen per case:

- Argument errors run the real script as a subprocess. argparse rejects them
  before anything touches the host, so nothing needs stubbing and the exit
  status is the one a caller actually sees.
- The sd dry run runs `main()` in process, because its first guard,
  `assert_safe_block_device`, needs a real whole-disk block device (a
  `Path.is_block_device()` stat plus a /sys/block entry) that no stub on PATH
  can provide. Only that one guard is replaced; everything after it - deploy
  and machine resolution, payload lookup, the freshness check, the fwup
  command line and the dry-run close-out - runs unmodified.

Output is normalised so a golden can be compared byte for byte: the temporary
root becomes `<TMP>`, timestamps are pinned with os.utime and rendered in UTC,
and argparse's usage wrapping is pinned with COLUMNS.
"""

from __future__ import annotations

import contextlib
import io
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
SCRIPT = SCRIPTS_DIR / "avocado-flash"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

MACHINE = "fixture-machine"
SD_DEVICE = "/dev/fixture-sd"
TMP_TOKEN = "<TMP>"

# 2026-01-02 03:04:00 UTC for the build output, one hour later for the archive,
# so the payload is fresh and assert_payload_fresh lets it through.
BUILD_MTIME = 1767323040
ARCHIVE_MTIME = BUILD_MTIME + 3600

STUB_TOOLS = ("fwup", "uuu", "sudo", "udevadm", "lsblk", "bmaptool", "lsusb")
SUBPROCESS_TIMEOUT = 30


def load_avocado_flash(name: str = "avocado_flash_under_test"):
    """Import scripts/avocado-flash as a module without running its main guard."""
    loader = SourceFileLoader(name, str(SCRIPT))
    spec = spec_from_loader(name, loader)
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


def make_deploy(root: Path) -> Path:
    """A deploy tree holding exactly one machine and a fresh fwup archive."""
    deploy = root / "build" / "tmp" / "deploy"
    images = deploy / "images" / MACHINE
    images.mkdir(parents=True)
    for name in ("imx-boot", "Image", f"{MACHINE}.wic"):
        f = images / name
        f.write_bytes(b"fixture\n")
        os.utime(f, (BUILD_MTIME, BUILD_MTIME))

    build = deploy / "stone" / "_build"
    build.mkdir(parents=True)
    archive = build / f"{MACHINE}-rootdisk.zip"
    archive.write_bytes(b"PK fixture archive\n")
    os.utime(archive, (ARCHIVE_MTIME, ARCHIVE_MTIME))
    return deploy


def make_stub_bin(root: Path) -> tuple[Path, Path]:
    """Stub executables that append their argv to a log and succeed.

    A dry run must execute none of them, so the log staying empty is the
    evidence that it did not.
    """
    bindir = root / "stub-bin"
    bindir.mkdir()
    log = root / "stub-calls.log"
    log.write_text("")
    for tool in STUB_TOOLS:
        stub = bindir / tool
        stub.write_text(f'#!/bin/sh\nprintf \'%s\\n\' "{tool} $*" >> "{log}"\nexit 0\n')
        stub.chmod(0o755)
    return bindir, log


@dataclass
class Result:
    exit: int
    stdout: str
    stderr: str


def normalise(text: str, root: Path) -> str:
    for form in {str(root.resolve()), str(root)}:
        text = text.replace(form, TMP_TOKEN)
    return text


@contextlib.contextmanager
def _utc():
    old = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


def run_main_in_process(module, argv: list[str], monkeypatch, bindir: Path) -> Result:
    """Run module.main() as the script's own __main__ guard would.

    The guard maps Fatal to exit 1 with `avocado-flash: <msg>` on stderr and
    KeyboardInterrupt to 130; argparse raises SystemExit itself.
    """
    monkeypatch.setattr(sys, "argv", ["avocado-flash", *argv])
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    for var in ("MACHINE", "BUILDDIR"):
        monkeypatch.delenv(var, raising=False)

    out, err = io.StringIO(), io.StringIO()
    with _utc(), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = module.main()
        except module.Fatal as exc:
            print(f"avocado-flash: {exc}", file=sys.stderr)
            code = 1
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    return Result(code, out.getvalue(), err.getvalue())


def run_script(argv: list[str], root: Path, bindir: Path) -> Result:
    """Run the real script in its own session, output to files, bounded wait."""
    env = {
        "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(root),
        "COLUMNS": "80",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "NO_COLOR": "1",
        "PYTHON_COLORS": "0",
    }
    out_path, err_path = root / "script.stdout", root / "script.stderr"
    with open(out_path, "wb") as out, open(err_path, "wb") as err:
        child = subprocess.Popen(
            [sys.executable, str(SCRIPT), *argv],
            stdin=subprocess.DEVNULL, stdout=out, stderr=err,
            cwd=root, env=env, start_new_session=True,
        )
        try:
            code = child.wait(timeout=SUBPROCESS_TIMEOUT)
        except subprocess.TimeoutExpired:
            # Only ever the child's own group: it was started as a session
            # leader, so its pgid equals its pid.
            if os.getpgid(child.pid) == child.pid:
                os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            raise
    return Result(code, out_path.read_text(), err_path.read_text())


def render_case(name: str, argv: list[str], result: Result, root: Path) -> str:
    return (
        f"=== CASE {name}\n"
        f"argv: {normalise(' '.join(argv), root)}\n"
        f"exit: {result.exit}\n"
        "--- stdout\n"
        f"{normalise(result.stdout, root)}"
        "--- stderr\n"
        f"{normalise(result.stderr, root)}"
    )


def golden_cases(path: Path) -> dict[str, str]:
    """Split a golden file into its `=== CASE <name>` sections, verbatim."""
    cases: dict[str, str] = {}
    current = None
    for line in path.read_text().splitlines(keepends=True):
        if line.startswith("=== CASE "):
            current = line[len("=== CASE "):].strip()
            cases[current] = ""
        if current is not None:
            cases[current] += line
    return cases
