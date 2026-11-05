import ast
import inspect
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from avocado_tegraflash import runner as runner_mod
from avocado_tegraflash.runner import SubprocessRunner

PKG_PARENT = Path(runner_mod.__file__).resolve().parent.parent


def test_runner_source_never_uses_a_shell():
    tree = ast.parse(inspect.getsource(runner_mod))
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "shell":
            pytest.fail("shell= keyword used")
        if isinstance(node, ast.Attribute) and node.attr in {"system", "popen", "getoutput", "getstatusoutput"}:
            pytest.fail(f"shell-running call {node.attr}")


def test_runner_passes_argument_list_to_subprocess(monkeypatch):
    seen = {}

    class FakePopen:
        def __init__(self, argv, **kw):
            seen["argv"], seen["kw"] = argv, kw
            if kw.get("stdout") is not None:
                kw["stdout"].write(b"x")

        def wait(self, timeout=None):
            return 3

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    assert SubprocessRunner().run(["a b", "; c"]) == 3
    assert seen["argv"] == ["a b", "; c"] and isinstance(seen["argv"], list)
    assert not seen["kw"].get("shell")
    assert SubprocessRunner().capture(["a"]) == (3, "x")
    assert not seen["kw"].get("shell")


@pytest.mark.parametrize("exc", [FileNotFoundError, PermissionError])
def test_unstartable_program_returns_127(monkeypatch, exc):
    def boom(*a, **k):
        raise exc()

    monkeypatch.setattr(subprocess, "Popen", boom)
    assert SubprocessRunner().run(["nope"]) == 127
    assert SubprocessRunner().capture(["nope"]) == (127, "")


INTERRUPT_CHILD = (
    "import pathlib, signal, sys, time\n"
    "armed, marker = sys.argv[1], sys.argv[2]\n"
    "def on_int(signum, frame):\n"
    "    time.sleep(1)\n"
    "    pathlib.Path(marker).write_text('cleaned up')\n"
    "    sys.exit(0)\n"
    "signal.signal(signal.SIGINT, on_int)\n"
    "pathlib.Path(armed).write_text('armed')\n"
    "time.sleep(30)\n"
    "sys.exit(9)\n"
)


def _interrupt_run(tmp_path, pkg_parent, interrupts=1):
    """Interrupt a runner mid-run with a child that needs a second to clean up."""
    child_script = tmp_path / "child.py"
    child_script.write_text(INTERRUPT_CHILD)
    armed, marker = tmp_path / "armed", tmp_path / "marker"
    helper = tmp_path / "helper.py"
    helper.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(pkg_parent)!r})\n"
        "from avocado_tegraflash.runner import SubprocessRunner\n"
        "SubprocessRunner().run([sys.executable, sys.argv[1], sys.argv[2], sys.argv[3]])\n"
    )
    out = tmp_path / "helper.out"
    with out.open("w") as fh:
        proc = subprocess.Popen(
            [sys.executable, "-I", "-B", str(helper), str(child_script), str(armed), str(marker)],
            stdout=fh, stderr=subprocess.STDOUT, start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 8
            while not armed.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert armed.exists(), out.read_text()
            assert os.getpgid(proc.pid) == proc.pid
            for _ in range(interrupts):
                os.killpg(proc.pid, signal.SIGINT)
                time.sleep(0.2)
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if os.getpgid(proc.pid) == proc.pid:
                os.killpg(proc.pid, signal.SIGKILL)
            pytest.fail("helper overran 10 seconds")
    return proc.returncode, out.read_text(), marker


@pytest.mark.real_subprocess
def test_interrupt_waits_for_child_cleanup_then_reraises(tmp_path):
    code, text, marker = _interrupt_run(tmp_path, PKG_PARENT)
    assert marker.read_text() == "cleaned up", text
    assert code != 0 and "KeyboardInterrupt" in text, text


@pytest.mark.real_subprocess
def test_a_second_interrupt_does_not_cut_the_wait_short(tmp_path):
    code, text, marker = _interrupt_run(tmp_path, PKG_PARENT, interrupts=2)
    assert marker.read_text() == "cleaned up", text
    assert code != 0 and "KeyboardInterrupt" in text, text


def test_runner_has_no_signalling_escalation():
    source = inspect.getsource(runner_mod)
    assert not any(word in source for word in (".terminate(", ".kill(", "GRACE"))


@pytest.mark.real_subprocess
def test_interrupt_test_fails_on_plain_subprocess_run(tmp_path):
    mutant = tmp_path / "mutant"
    shutil.copytree(PKG_PARENT / "avocado_tegraflash", mutant / "avocado_tegraflash", ignore=shutil.ignore_patterns("__pycache__"))
    target = mutant / "avocado_tegraflash" / "runner.py"
    src = target.read_text()
    old = "return _wait_through_interrupt(subprocess.Popen(list(argv), cwd=cwd, env=env))"
    assert src.count(old) == 1
    target.write_text(src.replace(old, "return subprocess.run(list(argv), cwd=cwd, env=env, check=False).returncode"))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    _, _, marker = _interrupt_run(scratch, mutant)
    assert not marker.exists()


@pytest.mark.real_subprocess
def test_real_programs(tmp_path):
    """Real tiny programs, in their own process group, 10 s bound, output to a file."""
    script = tmp_path / "probe.py"
    out = tmp_path / "out.txt"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(PKG_PARENT)!r})\n"
        "from avocado_tegraflash.runner import SubprocessRunner\n"
        "r = SubprocessRunner()\n"
        "py = sys.executable\n"
        "print('run', r.run([py, '-c', 'import sys; sys.exit(7)']))\n"
        "print('cap', r.capture([py, '-c', 'print(\"hi\")']))\n"
        "print('missing', r.run(['/nonexistent/prog']))\n"
        "print('noexec', r.run([sys.argv[1]]))\n"
        "print('shellchars', r.capture(['echo', '$HOME; true']))\n"
    )
    plain = tmp_path / "plain"
    plain.write_text("x")
    plain.chmod(0o644)
    with out.open("w") as fh:
        child = subprocess.Popen(
            [sys.executable, "-I", "-B", str(script), str(plain)],
            stdout=fh, stderr=subprocess.STDOUT, start_new_session=True,
        )
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if os.getpgid(child.pid) == child.pid:
                os.killpg(child.pid, signal.SIGTERM)
            pytest.fail("probe overran 10 seconds")
    text = out.read_text()
    assert child.returncode == 0, text
    assert "run 7" in text
    assert "cap (0, 'hi\\n')" in text
    assert "missing 127" in text
    assert "noexec 127" in text
    assert "shellchars (0, '$HOME; true\\n')" in text


# ---- capture: stderr discard and wall-clock timeout -----------------------


def _probe(tmp_path, body, pkg_parent=PKG_PARENT):
    """Run `body` (python text using SubprocessRunner as `r`) in its own session; return (status, stdout, stderr)."""
    script = tmp_path / "probe.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(pkg_parent)!r})\n"
        "from avocado_tegraflash.runner import SubprocessRunner\n"
        "r = SubprocessRunner()\n" + body
    )
    out, err = tmp_path / "probe.out", tmp_path / "probe.err"
    with out.open("w") as fo, err.open("w") as fe:
        child = subprocess.Popen(
            [sys.executable, "-I", "-B", str(script)], stdout=fo, stderr=fe, stdin=subprocess.DEVNULL, start_new_session=True
        )
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            if os.getpgid(child.pid) == child.pid:
                os.killpg(child.pid, signal.SIGKILL)
            pytest.fail("probe overran 15 seconds")
    return child.returncode, out.read_text(), err.read_text()


NOISY = "import sys; print('out'); print('noise', file=sys.stderr)"


@pytest.mark.real_subprocess
def test_capture_without_discard_lets_the_child_stderr_through(tmp_path):
    code, out, err = _probe(tmp_path, f"print(r.capture([sys.executable, '-c', {NOISY!r}]))\n")
    assert (code, out, err) == (0, "(0, 'out\\n')\n", "noise\n")


@pytest.mark.real_subprocess
def test_capture_with_discard_stderr_keeps_the_engine_stderr_empty_and_returns_stdout(tmp_path):
    body = f"print(r.capture([sys.executable, '-c', {NOISY!r}], discard_stderr=True))\n"
    assert _probe(tmp_path, body) == (0, "(0, 'out\\n')\n", "")


def _timeout_probe_body(pidfile):
    child = (
        "import os, subprocess, sys, time\n"
        f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(pidfile)!r}, 'w').write(f'{{os.getpid()}} {{p.pid}}')\n"
        "time.sleep(60)\n"
    )
    return (
        "import time\n"
        "t = time.monotonic()\n"
        f"res = r.capture([sys.executable, '-c', {child!r}], timeout=1.0)\n"
        "print(res, round(time.monotonic() - t) < 5)\n"
    )


def _gone(pid):
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False



_LEAVER = 'setsid sh -c "echo \\$\\$ > $1; exec sleep 6" & '


def _leaver_body(pidfile, tail):
    argv = ["sh", "-c", _LEAVER + tail, "sh", str(pidfile)]
    return (
        "import time\n"
        "t = time.monotonic()\n"
        f"res = r.capture({argv!r}, timeout=1.0)\n"
        "print(res, round(time.monotonic() - t) < 4)\n"
    )


def _kill_leaver(pidfile):
    """The descendant left the group via setsid; kill it by the pid it wrote, never by name."""
    if pidfile.exists() and pidfile.read_text().strip():
        try:
            os.kill(int(pidfile.read_text()), signal.SIGKILL)
        except ProcessLookupError:
            pass


@pytest.mark.real_subprocess
def test_capture_timeout_holds_even_when_a_descendant_left_the_group_and_holds_stdout(tmp_path):
    pidfile = tmp_path / "pid"
    try:
        code, out, err = _probe(tmp_path, _leaver_body(pidfile, "sleep 30"))
    finally:
        _kill_leaver(pidfile)
    assert (code, out, err) == (0, "(124, '') True\n", "")


@pytest.mark.real_subprocess
def test_capture_returns_the_real_status_when_the_command_exits_with_a_lingering_descendant(tmp_path):
    pidfile = tmp_path / "pid"
    try:
        code, out, err = _probe(tmp_path, _leaver_body(pidfile, "echo seen; exit 3"))
    finally:
        _kill_leaver(pidfile)
    assert (code, out, err) == (0, "(3, 'seen\\n') True\n", "")


@pytest.mark.real_subprocess
def test_capture_timeout_is_status_124_bounded_and_leaves_no_orphan(tmp_path):
    pidfile = tmp_path / "pids"
    code, out, err = _probe(tmp_path, _timeout_probe_body(pidfile))
    assert (code, out, err) == (0, "(124, '') True\n", "")
    parent, grandchild = (int(n) for n in pidfile.read_text().split())
    assert (_gone(parent), _gone(grandchild)) == (True, True)


@pytest.mark.real_subprocess
def test_capture_timeout_test_fails_when_only_the_direct_child_is_killed_and_a_grandchild_survives(tmp_path):
    mutant = tmp_path / "mutant"
    shutil.copytree(PKG_PARENT / "avocado_tegraflash", mutant / "avocado_tegraflash", ignore=shutil.ignore_patterns("__pycache__"))
    target = mutant / "avocado_tegraflash" / "runner.py"
    src = target.read_text()
    old = "os.killpg(proc.pid, signal.SIGKILL)"
    assert src.count(old) == 1
    target.write_text(src.replace(old, "proc.kill()"))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    pidfile = scratch / "pids"
    try:
        _probe(scratch, _timeout_probe_body(pidfile), pkg_parent=mutant)
        leader, grandchild = (int(n) for n in pidfile.read_text().split())
        os.kill(grandchild, 0)  # the mutant left the grandchild running
    finally:
        if pidfile.exists():
            leader, grandchild = (int(n) for n in pidfile.read_text().split())
            try:
                if os.getpgid(grandchild) == leader:
                    os.killpg(leader, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.real_subprocess
def test_capture_discard_test_fails_when_stderr_is_not_discarded(tmp_path):
    mutant = tmp_path / "mutant"
    shutil.copytree(PKG_PARENT / "avocado_tegraflash", mutant / "avocado_tegraflash", ignore=shutil.ignore_patterns("__pycache__"))
    target = mutant / "avocado_tegraflash" / "runner.py"
    src = target.read_text()
    old = "stderr=subprocess.DEVNULL if discard_stderr else None,"
    assert src.count(old) == 1
    target.write_text(src.replace(old, "stderr=None,"))
    body = f"print(r.capture([sys.executable, '-c', {NOISY!r}], discard_stderr=True))\n"
    _, _, err = _probe(tmp_path, body, pkg_parent=mutant)
    assert err == "noise\n"
