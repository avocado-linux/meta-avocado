"""Runner dispatcher and single-archive bundle."""

import ast
import hashlib
import json
import os
import subprocess
import sys
import textwrap
import time
import zipfile
from pathlib import Path

import pytest

from avocado_flash_remote import bundle, ops, runner

PKG = Path(bundle.__file__).resolve().parent
FIXTURE = PKG / "profiles" / "fixture-none.json"


def _run(cmd, tmp_path, name, timeout=60, stdin=subprocess.DEVNULL):
    """Run cmd in its own session, output to files; return (rc, out, err)."""
    out = tmp_path / f"{name}.out"
    err = tmp_path / f"{name}.err"
    with open(out, "wb") as fo, open(err, "wb") as fe:
        child = subprocess.Popen(cmd, stdin=stdin, stdout=fo, stderr=fe, start_new_session=True)
        try:
            rc = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.getpgid(child.pid) == child.pid:
                os.killpg(child.pid, 9)
            child.wait()
            raise
    return rc, out.read_text(), err.read_text()


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp("bundle")
    data = FIXTURE.read_bytes()
    info = bundle.build_bundle(data, d / "bundle.pyz", "test-1")
    return info, data


# ------------------------------------------------------------------ bundle


def test_archive_runs_version(built, tmp_path):
    info, _ = built
    rc, out, err = _run([sys.executable, str(info.path), "--version"], tmp_path, "v")
    assert rc == 0, err
    assert out.splitlines()[0] == f"avocado-flash-runner {runner.RUNNER_VERSION}"
    assert any(ln.startswith("bundle sha256 ") for ln in out.splitlines())


def test_archive_runs_under_python310(built, tmp_path):
    info, _ = built
    rc, out, err = _run(
        ["uv", "run", "--python", "3.10", "python3", str(info.path), "--version"], tmp_path, "v310", timeout=180
    )
    assert rc == 0, err
    assert out.startswith("avocado-flash-runner ")


def test_every_member_compiles_under_python310(built, tmp_path):
    info, _ = built
    script = tmp_path / "grammar.py"
    script.write_text(
        textwrap.dedent(
            """
            import sys, zipfile
            assert sys.version_info[:2] == (3, 10), sys.version
            z = zipfile.ZipFile(sys.argv[1])
            n = 0
            for name in z.namelist():
                if name.endswith(".py"):
                    compile(z.read(name), name, "exec")
                    n += 1
            print("compiled", n)
            """
        )
    )
    rc, out, err = _run(["uv", "run", "--python", "3.10", "python3", str(script), str(info.path)], tmp_path, "g", 180)
    assert rc == 0, err
    assert int(out.split()[-1]) == len(info.modules) + 1  # modules + __main__.py


def test_deterministic(tmp_path):
    data = FIXTURE.read_bytes()
    a = bundle.build_bundle(data, tmp_path / "a.pyz", "t")
    b = bundle.build_bundle(data, tmp_path / "b.pyz", "t")
    assert (tmp_path / "a.pyz").read_bytes() == (tmp_path / "b.pyz").read_bytes()
    assert a.sha256 == b.sha256 == hashlib.sha256((tmp_path / "a.pyz").read_bytes()).hexdigest()


def test_mode_and_shebang(built):
    info, _ = built
    assert info.path.stat().st_mode & 0o777 == 0o755
    assert info.path.read_bytes().startswith(b"#!/usr/bin/env python3\n")


def test_profile_bytes_exact(built):
    info, data = built
    with zipfile.ZipFile(info.path) as z:
        assert z.read("profile.json") == data
    assert info.profile_sha256 == hashlib.sha256(data).hexdigest()


def test_bundle_json_lists_modules_with_hashes(built):
    info, data = built
    with zipfile.ZipFile(info.path) as z:
        meta = json.loads(z.read("BUNDLE.json"))
        assert meta["profile_sha256"] == info.profile_sha256
        assert meta["tool_version"] == "test-1"
        assert meta["runner_version"] == runner.RUNNER_VERSION
        for name, digest in meta["modules"].items():
            assert hashlib.sha256(z.read(name)).hexdigest() == digest
    assert "avocado_flash_remote/runner.py" in meta["modules"]
    for host_only in ("cli", "host", "bundle", "profile_resolve"):
        assert f"avocado_flash_remote/{host_only}.py" not in meta["modules"]


def test_verify_clean_and_detects_tamper(built, tmp_path):
    info, _ = built
    assert bundle.verify_bundle(info.path) == []
    bad = tmp_path / "bad.pyz"
    with zipfile.ZipFile(info.path) as src, zipfile.ZipFile(bad, "w") as dst:
        for item in src.infolist():
            body = src.read(item.filename)
            if item.filename == "avocado_flash_remote/ops.py":
                body += b"\n# tampered\n"
            dst.writestr(item, body)
    problems = bundle.verify_bundle(bad)
    assert any("avocado_flash_remote/ops.py" in p for p in problems)


def _module_dir(tmp_path, extra):
    d = tmp_path / "mods"
    d.mkdir()
    for p in PKG.glob("*.py"):
        (d / p.name).write_bytes(p.read_bytes())
    (d / "arm.py").write_text((PKG / "arm.py").read_text() + "\n" + extra + "\n")
    return d


def test_non_stdlib_import_refused(tmp_path):
    d = _module_dir(tmp_path, "import requests")
    with pytest.raises(bundle.BundleError, match="requests"):
        bundle.build_bundle(FIXTURE.read_bytes(), tmp_path / "x.pyz", "t", modules_dir=d)


def test_non_stdlib_from_import_refused(tmp_path):
    d = _module_dir(tmp_path, "from yaml import safe_load")
    with pytest.raises(bundle.BundleError, match="yaml"):
        bundle.build_bundle(FIXTURE.read_bytes(), tmp_path / "x.pyz", "t", modules_dir=d)


def test_missing_required_module_refused(tmp_path):
    d = _module_dir(tmp_path, "")
    (d / "cmd_write.py").unlink()
    with pytest.raises(bundle.BundleError, match="cmd_write"):
        bundle.build_bundle(FIXTURE.read_bytes(), tmp_path / "x.pyz", "t", modules_dir=d)


def test_shipped_modules_only_import_stdlib():
    allowed = set(sys.stdlib_module_names)
    for name in bundle.ARCHIVE_MODULES:
        tree = ast.parse((PKG / f"{name}.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] in allowed, (name, a.name)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                assert node.module.split(".")[0] in allowed or node.module.startswith("avocado_flash_remote"), (
                    name,
                    node.module,
                )


# ------------------------------------------------------------------ runner


def _archive_for_runner(tmp_path):
    data = FIXTURE.read_bytes()
    info = bundle.build_bundle(data, tmp_path / "r.pyz", "t")
    return info


def _request(tmp_path, **extra):
    req = {
        "staging_dir": "/stage",
        "state_dir": str(tmp_path / "state"),
        "run_dir": str(tmp_path / "run"),
        "run_id": "r1",
        "expected_boot_order": "0001,0002",
        "reference_boot_order": "0001",
        "ack_run_id": "ack1",
        "assume_yes": False,
        "confirmed_device": "/dev/loop-fixture",
        "emergency_disarm": True,
        "mount_dir": "/mnt/x",
        "out_dir": "/run/out",
        "efivars_dir": "/efi",
        "plan_path": str(tmp_path / "plan.json"),
    }
    req.update(extra)
    p = tmp_path / "req.json"
    p.write_text(json.dumps(req))
    return p


class _Rec:
    def __init__(self, code=0):
        self.calls = []
        self.code = code

    def __call__(self, *args, **kw):
        self.calls.append((args, kw))
        return type("R", (), {"exit_code": self.code})()


@pytest.fixture
def recs(monkeypatch):
    r = {}
    for n in ("check", "plan", "write", "restore", "readback", "status"):
        r[n] = _Rec(code=7 if n == "plan" else 0)
        monkeypatch.setattr(runner, f"run_{n}", r[n])
    return r


def test_unknown_subcommand_exit_64(tmp_path, capsys):
    info = _archive_for_runner(tmp_path)
    assert runner.main(["bogus"], archive=info.path) == 64
    out = capsys.readouterr()
    for name in ("check", "plan", "write", "restore", "readback", "status"):
        assert name in out.out + out.err


def test_wrong_profile_hash_exit_3(tmp_path, recs, capsys):
    info = _archive_for_runner(tmp_path)
    req = _request(tmp_path, profile_hash="0" * 64)
    assert runner.main(["check", "--request", str(req)], archive=info.path) == 3
    assert "profile" in capsys.readouterr().err
    assert not recs["check"].calls


def test_matching_profile_hash_accepted(tmp_path, recs):
    info = _archive_for_runner(tmp_path)
    req = _request(tmp_path, profile_hash=info.profile_sha256)
    assert runner.main(["status", "--request", str(req)], archive=info.path) == 0


def test_check_wiring(tmp_path, recs):
    info = _archive_for_runner(tmp_path)
    assert runner.main(["check", "--request", str(_request(tmp_path))], archive=info.path) == 0
    (args, kw), = recs["check"].calls
    assert isinstance(args[0], ops.ReadOnlyOps) and isinstance(args[0]._inner, ops.RealOps)
    assert args[1].board == "fixture-none"
    assert kw == {"staging_dir": "/stage", "efivars_dir": "/efi", "expected_boot_order": "0001,0002"}


def test_plan_wiring_and_exit_code(tmp_path, recs):
    info = _archive_for_runner(tmp_path)
    assert runner.main(["plan", "--request", str(_request(tmp_path))], archive=info.path) == 7
    (args, kw), = recs["plan"].calls
    assert isinstance(args[0], ops.ReadOnlyOps)
    assert args[2] == info.profile_sha256
    assert kw == {"staging_dir": "/stage", "run_dir": str(tmp_path / "run"), "run_id": "r1"}


def test_write_wiring(tmp_path, recs):
    info = _archive_for_runner(tmp_path)
    (tmp_path / "plan.json").write_text('{"run_id": "r1"}')
    assert runner.main(["write", "--request", str(_request(tmp_path))], archive=info.path) == 0
    (args, kw), = recs["write"].calls
    assert isinstance(args[0], ops.RealOps)
    assert args[2] == info.profile_sha256
    assert set(kw) == {
        "staging_dir", "state_dir", "run_dir", "plan_loader", "confirm", "assume_yes",
        "expected_boot_order", "efivars_dir", "ack_run_id",
    }  # fmt: skip
    assert kw["staging_dir"] == "/stage"
    assert kw["state_dir"] == str(tmp_path / "state")
    assert kw["run_dir"] == str(tmp_path / "run")
    assert kw["assume_yes"] is False
    assert kw["expected_boot_order"] == "0001,0002"
    assert kw["efivars_dir"] == "/efi"
    assert kw["ack_run_id"] == "ack1"
    assert kw["plan_loader"]() == {"run_id": "r1"}
    assert kw["confirm"]("/dev/anything") == "/dev/loop-fixture"


def test_restore_wiring(tmp_path, recs):
    info = _archive_for_runner(tmp_path)
    assert runner.main(["restore", "--request", str(_request(tmp_path))], archive=info.path) == 0
    (args, kw), = recs["restore"].calls
    assert isinstance(args[0], ops.RealOps)
    assert kw == {
        "state_dir": str(tmp_path / "state"),
        "staging_dir": "/stage",
        "ack_run_id": "ack1",
        "emergency_disarm": True,
    }


def test_readback_wiring(tmp_path, recs):
    info = _archive_for_runner(tmp_path)
    assert runner.main(["readback", "--request", str(_request(tmp_path))], archive=info.path) == 0
    (args, kw), = recs["readback"].calls
    assert isinstance(args[0], ops.RealOps)
    assert kw == {
        "state_dir": str(tmp_path / "state"),
        "mount_dir": "/mnt/x",
        "out_dir": "/run/out",
        "reference_boot_order": "0001",
    }


def test_status_wiring(tmp_path, recs):
    info = _archive_for_runner(tmp_path)
    assert runner.main(["status", "--request", str(_request(tmp_path))], archive=info.path) == 0
    (args, kw), = recs["status"].calls
    assert args == (str(tmp_path / "state"),) and kw == {}


def test_unexpected_exception_exit_70(tmp_path, monkeypatch, capsys):
    info = _archive_for_runner(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("kaput")

    monkeypatch.setattr(runner, "run_status", boom)
    assert runner.main(["status", "--request", str(_request(tmp_path))], archive=info.path) == 70
    assert "runner error: RuntimeError: kaput" in capsys.readouterr().err


def test_keyboard_interrupt_exit_130(tmp_path, monkeypatch):
    info = _archive_for_runner(tmp_path)

    def boom(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "run_status", boom)
    assert runner.main(["status", "--request", str(_request(tmp_path))], archive=info.path) == 130


# ------------------------------------------------------------------ detach


def test_detach(tmp_path):
    info = _archive_for_runner(tmp_path)
    run_dir = tmp_path / "run"
    marker = tmp_path / "marker.json"
    req = _request(tmp_path)
    (tmp_path / "plan.json").write_text('{"run_id": "r1"}')
    driver = tmp_path / "driver.py"
    driver.write_text(
        textwrap.dedent(
            f"""
            import json, os, sys, time
            sys.path.insert(0, {str(PKG.parent)!r})
            from avocado_flash_remote import runner

            DRIVER_SID, DRIVER_PID = os.getsid(0), os.getpid()

            def stub(*a, **k):
                fd0 = os.fstat(0)
                null = os.stat("/dev/null")
                print("from-stub-stdout")
                print("from-stub-stderr", file=sys.stderr)
                sys.stdout.flush(); sys.stderr.flush()
                with open({str(marker)!r}, "w") as f:
                    json.dump({{"pid": os.getpid(), "sid": os.getsid(0), "ppid": os.getppid(), "driver_sid": DRIVER_SID, "driver_pid": DRIVER_PID,
                               "stdin_null": (fd0.st_rdev == null.st_rdev) and (fd0.st_ino == null.st_ino)}}, f)
                time.sleep(0.5)
                return type("R", (), {{"exit_code": 0}})()

            runner.run_write = stub
            sys.exit(runner.main(["write", "--request", {str(req)!r}, "--detach"], archive={str(info.path)!r}))
            """
        )
    )
    t0 = time.monotonic()
    rc, out, err = _run([sys.executable, str(driver)], tmp_path, "d", timeout=20)
    elapsed = time.monotonic() - t0
    assert rc == 0, err
    assert elapsed < 2.0
    log = run_dir / "runner.log"
    assert out.strip() == f"detached: run=r1 log={log}"
    # wait for the grandchild to finish
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not marker.exists():
        time.sleep(0.05)
    m = json.loads(marker.read_text())
    assert m["stdin_null"] is True
    time.sleep(0.8)
    text = log.read_text()
    assert "from-stub-stdout" in text and "from-stub-stderr" in text
    assert log.stat().st_mode & 0o777 == 0o600
    assert m["sid"] != m["driver_sid"]  # setsid() left the launcher's session
    assert m["pid"] != m["driver_pid"]
    # status reads the (absent) state afterwards without error
    assert runner.main(["status", "--request", str(req)], archive=str(info.path)) == 0
