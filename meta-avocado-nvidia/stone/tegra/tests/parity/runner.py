"""Run one parity case through the frozen oracle or the engine.

Both sides get the same fixture tree, the same recording stubs and the same
minimal environment, so the only difference between two runs is the program
under test. Use a distinct workdir per side: each run writes its tree, call log
and scratch HOME below it.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

from parity import compare, fixtures, stubs
from parity.cases import Case

# The directory that holds the avocado_tegraflash package.
ENGINE_ROOT = Path(__file__).resolve().parents[2]
ORACLE = Path(__file__).resolve().parent / "legacy" / "stone-provision-tegraflash.sh"
TIMEOUT = 60
TREE_KEYS = ("carrier", "kernel", "drop", "shadow_link", "absolute_images", "tos_name")
WORKDIR = compare.WORKDIR_NAME
LOCK_FILE = WORKDIR + ".lock"
HOST_PATH = "/usr/bin:/bin"

# The oracle polls with the real sleep (up to 60 one-second waits); the stub
# keeps that instant and is infrastructure, so it is not one of STUB_TOOLS.
_NOOP_SLEEP = "#!/bin/sh\nexit 0\n"

# The real tools the oracle and the engine may start besides the stubs. PATH is
# the stub directory plus links to exactly these, so a program nothing intercepts
# cannot start unnoticed (design assumption A5).
HOST_TOOLS = (
    "awk",
    "basename",
    "bash",
    "cat",
    "chmod",
    "cp",
    "cut",
    "dirname",
    "env",
    "find",
    "grep",
    "head",
    "jq",
    "ls",
    "mkdir",
    "mktemp",
    "python3",
    "readlink",
    "rm",
    "sed",
    "seq",
    "sh",
    "sort",
    "tail",
    "tr",
    "uname",
    "wc",
)

# Bare program names that are not found on PATH are appended here, by bash's
# command_not_found_handle on the oracle side and by the driver's Popen hook on
# the engine side. The engine side also records an absolute argv[0] outside the
# PATH directories (stubs and allowlist links). The oracle side cannot: bash
# runs an existing absolute path without calling any handler, and a DEBUG trap
# would change the oracle's behaviour.
_BASH_HOOK = """\
command_not_found_handle() {
  printf '%s\\n' "$1" >> "$PARITY_UNSTUBBED_LOG"
  return 127
}
"""

_DRIVER = """\
import os, subprocess, sys
sys.path.insert(0, sys.argv[1])
from avocado_tegraflash.cli import main

_init = subprocess.Popen.__init__


def _hooked(self, args, *a, **k):
    first = str(args if isinstance(args, str) else (list(args) or [""])[0])
    if first.startswith("/") and os.path.dirname(first) not in os.environ["PATH"].split(":"):
        with open(os.environ["PARITY_UNSTUBBED_LOG"], "a") as fh:
            fh.write(first + "\\n")
    try:
        _init(self, args, *a, **k)
    except (FileNotFoundError, PermissionError):
        name = args if isinstance(args, str) else (list(args) or [""])[0]
        if "/" not in str(name):
            with open(os.environ["PARITY_UNSTUBBED_LOG"], "a") as fh:
                fh.write(str(name) + "\\n")
        raise


subprocess.Popen.__init__ = _hooked
sys.exit(main(sys.argv[2:], environ=dict(os.environ), euid=0, sleep=lambda _s: None))
"""


class OracleUnavailable(RuntimeError):
    """The oracle cannot run on this host (no jq); the case counts as not run."""


class Result(NamedTuple):
    exit_status: int
    calls: list
    snapshot: dict
    unstubbed: tuple  # bare program names started that were neither stub nor allowlisted
    outside_changes: tuple  # paths outside the work directory that the run changed


class Setup(NamedTuple):
    workdir: Path
    tree: fixtures.Tree
    log_path: Path
    home: Path


def setup(case: Case, workdir) -> Setup:
    workdir = Path(workdir)
    extra = set(case.tree) - set(TREE_KEYS)
    if extra:
        raise ValueError(f"unsupported tree keywords: {', '.join(sorted(extra))}")
    stub_dir = workdir / "stubs"
    log_path = workdir / "calls.jsonl"
    scenario_path = workdir / "scenario.json"
    home = workdir / "home"
    home.mkdir(parents=True, exist_ok=True)
    scenario_path.write_text(json.dumps(case.scenario))
    stubs.write_stubs(stub_dir, log_path, scenario_path)
    sleep = stub_dir / "sleep"
    sleep.write_text(_NOOP_SLEEP)
    sleep.chmod(0o755)
    _link_host_tools(workdir / "hostbin")
    (workdir / "hooks.sh").write_text(_BASH_HOOK)
    tree = fixtures.build_tree(case.manifest, workdir / "tree", stub_dir, **case.tree)
    return Setup(workdir, tree, log_path, home)


def _link_host_tools(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in HOST_TOOLS:
        found = shutil.which(name, path=HOST_PATH)
        if found is not None:
            (directory / name).symlink_to(found)


def build_env(case: Case, s: Setup) -> dict[str, str]:
    env = {
        "PATH": f"{s.tree.stub_dir}:{s.workdir / 'hostbin'}",
        "HOME": str(s.home),
        "BASH_ENV": str(s.workdir / "hooks.sh"),
        "PARITY_UNSTUBBED_LOG": str(s.workdir / "unstubbed.log"),
        "AVOCADO_STONE_MANIFEST": str(s.tree.manifest),
        "AVOCADO_STONE_BUILD_DIR": str(s.tree.build_dir),
        "AVOCADO_STONE_DATA_DIR": str(s.tree.data_dir),
        "AVOCADO_PROVISION_PROFILE": case.profile,
        # Never let a typed confirmation block a run that has no terminal.
        "AVOCADO_PROVISION_FORCE": "1",
    }
    if s.tree.kernel_image is not None:
        env["AVOCADO_PROVISION_KERNEL_IMAGE"] = str(s.tree.kernel_image)
    env.update(case.env_dict)
    return env


def read_calls(log_path) -> list:
    try:
        text = Path(log_path).read_text()
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def snapshot_of(work_dir, calls) -> dict:
    if not Path(work_dir).is_dir():
        return {}
    return compare.snapshot(work_dir, compare.extract_partuuids(calls))


def run_in_own_session(argv, *, timeout: float, stdout, stderr=subprocess.STDOUT, **popen) -> int:
    """Run argv in its own session; on timeout stop only that session's group, then re-raise.

    Output goes to files the caller opened (never a pipe a full buffer could
    block on). The group is signalled only after confirming the child leads it.
    """
    child = subprocess.Popen(argv, stdout=stdout, stderr=stderr, start_new_session=True, **popen)
    try:
        return child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.getpgid(child.pid) == child.pid:
            os.killpg(child.pid, signal.SIGKILL)
        child.wait()
        raise


def _spawn(argv: list[str], env: dict, cwd: Path, workdir: Path, name: str) -> int:
    with open(workdir / f"{name}.out", "wb") as out, open(workdir / f"{name}.err", "wb") as err:
        return run_in_own_session(
            argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=TIMEOUT
        )


def outside_snapshot(tree: fixtures.Tree) -> dict:
    """Everything a run must leave alone: the data directory, the sentinel
    directory beside both trees, and the build directory except the work
    directory itself and its lock file."""
    snap = {}
    for area, directory in (("data", tree.data_dir), ("outside", tree.outside_dir), ("build", tree.build_dir)):
        for rel, entry in compare.snapshot(directory, {}).items():
            if area == "build" and (rel == WORKDIR or rel.startswith(WORKDIR + "/")):
                continue
            # Deviation build-dir-locked: the engine's lock file, which the oracle never creates.
            if area == "build" and rel == LOCK_FILE:
                continue
            snap[f"{area}/{rel}"] = entry
    return snap


def _unstubbed(workdir: Path) -> tuple:
    try:
        text = (workdir / "unstubbed.log").read_text()
    except FileNotFoundError:
        return ()
    return tuple(sorted(set(text.split())))


def _finish(s: Setup, status: int, before: dict) -> Result:
    calls = read_calls(s.log_path)
    changes = compare.diff_snapshots(before, outside_snapshot(s.tree))
    return Result(
        status,
        calls,
        snapshot_of(s.tree.build_dir / WORKDIR, calls),
        _unstubbed(s.workdir),
        tuple(changes),
    )


def run_oracle(case: Case, workdir) -> Result:
    if shutil.which("jq", path=HOST_PATH) is None:
        raise OracleUnavailable("jq is not installed; the oracle cannot run")
    s = setup(case, workdir)
    before = outside_snapshot(s.tree)
    status = _spawn(["/bin/bash", str(ORACLE)], build_env(case, s), s.tree.data_dir, s.workdir, "oracle")
    return _finish(s, status, before)


def run_engine(case: Case, workdir, engine_root=None, argv=()) -> Result:
    root = Path(engine_root) if engine_root is not None else ENGINE_ROOT
    s = setup(case, workdir)
    cmd = [sys.executable, "-I", "-B", "-c", _DRIVER, str(root), *argv]
    before = outside_snapshot(s.tree)
    status = _spawn(cmd, build_env(case, s), s.tree.data_dir, s.workdir, "engine")
    return _finish(s, status, before)
