"""Tests for the subprocess runner.

Every test runs only tiny scripts created under tmp_path that use shell
builtins and finish by themselves.
"""

import collections
import os
import pathlib

import pytest

from avocado_flash_tegra import FlashError
from avocado_flash_tegra.runner import Interrupted, SubprocessRunner

pytestmark = pytest.mark.real_subprocess

Inv = collections.namedtuple("Inv", "argv env cwd")


def _script(tmp_path, body):
    path = tmp_path / "script.sh"
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


def _inv(tmp_path, script):
    return Inv(argv=[str(script)], env=dict(os.environ), cwd=str(tmp_path))


def test_stream_orders_both_streams_identically_and_returns_status(tmp_path):
    script = _script(
        tmp_path,
        "echo out1\necho err1 >&2\necho out2\necho err2 >&2\nexit 3\n",
    )
    log = tmp_path / "run.log"
    seen = []
    rc = SubprocessRunner().stream(_inv(tmp_path, script), log, echo=seen.append)
    assert rc == 3
    assert seen == ["out1", "err1", "out2", "err2"]
    assert log.read_text() == "out1\nerr1\nout2\nerr2\n"


def test_stream_uses_invocation_cwd_and_env(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    script = _script(tmp_path, 'echo "$PWD"\necho "$MARK"\n')
    env = dict(os.environ, MARK="marker-value")
    inv = Inv(argv=[str(script)], env=env, cwd=str(work))
    seen = []
    rc = SubprocessRunner().stream(inv, tmp_path / "l.log", echo=seen.append)
    assert rc == 0
    assert seen == [str(work.resolve()), "marker-value"]


def test_capture_missing_executable_returns_127(tmp_path):
    rc, out = SubprocessRunner().capture([str(tmp_path / "does-not-exist")])
    assert rc == 127
    assert "does-not-exist" in out


def test_capture_returns_status_and_stdout(tmp_path):
    script = _script(tmp_path, "echo hello\nexit 4\n")
    rc, out = SubprocessRunner().capture([str(script)])
    assert rc == 4
    assert out == "hello\n"


def test_interrupt_waits_for_child_then_raises(tmp_path):
    marker = tmp_path / "done.marker"
    script = _script(
        tmp_path,
        "echo first\n"
        "i=0\n"
        "while [ $i -lt 200000 ]; do i=$((i+1)); done\n"
        f': > "{marker}"\n'
        "echo last\n",
    )
    log = tmp_path / "run.log"

    def echo(line):
        raise KeyboardInterrupt

    with pytest.raises(Interrupted) as exc:
        SubprocessRunner().stream(_inv(tmp_path, script), log, echo=echo)
    assert isinstance(exc.value, FlashError)
    assert marker.exists()
    assert log.read_text() == "first\nlast\n"


def test_child_sees_only_the_invocation_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("AVOCADO_AGENT_SOCK", "/run/leak.sock")
    monkeypatch.setenv("SECRET_X", "hunter2")
    out = tmp_path / "child-env.txt"
    script = _script(tmp_path, f'export -p > "{out}"\n')
    inv = Inv(argv=[str(script)], env={"MARK": "kept"}, cwd=str(tmp_path))
    assert SubprocessRunner().stream(inv, tmp_path / "l.log", echo=lambda line: None) == 0
    text = out.read_text()
    assert "MARK" in text
    assert "AVOCADO_AGENT_SOCK" not in text
    assert "SECRET_X" not in text
    assert "hunter2" not in text
