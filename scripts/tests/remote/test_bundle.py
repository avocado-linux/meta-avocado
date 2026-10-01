"""Runner dispatcher and single-archive bundle."""

import ast
import dataclasses
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
        "run_dir": str(tmp_path / "state" / "r1" / "records"),
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


@pytest.fixture(autouse=True)
def _state_under_tmp(tmp_path, monkeypatch):
    """Point the fixture profile's state_dir at tmp_path/state for runner.main."""
    real = runner.load_profile_bytes
    monkeypatch.setattr(
        runner, "load_profile_bytes", lambda b: dataclasses.replace(real(b), state_dir=str(tmp_path / "state"))
    )


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
    assert kw == {"staging_dir": "/stage", "run_dir": str(tmp_path / "state" / "r1" / "records"), "run_id": "r1"}


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
    assert kw["run_dir"] == str(tmp_path / "state" / "r1" / "records")
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
    run_dir = tmp_path / "state" / "r1" / "records"
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

            import dataclasses
            _real = runner.load_profile_bytes
            runner.load_profile_bytes = lambda b: dataclasses.replace(_real(b), state_dir={str(tmp_path / "state")!r})
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


# ------------------------------------------------------------ run_dir (5.11)


def _main(sub, tmp_path, **extra):
    info = _archive_for_runner(tmp_path)
    return runner.main([sub, "--request", str(_request(tmp_path, **extra))], archive=info.path)


@pytest.mark.parametrize("sub", ["plan", "write", "restore", "readback"])
def test_run_dir_created_0700_for_mutating_subs(tmp_path, recs, sub):
    (tmp_path / "plan.json").write_text("{}")
    old = os.umask(0)  # mode must not depend on the umask
    try:
        _main(sub, tmp_path)
    finally:
        os.umask(old)
    rd = tmp_path / "state" / "r1" / "records"
    assert rd.is_dir() and rd.stat().st_mode & 0o777 == 0o700
    assert (tmp_path / "state" / "r1").stat().st_mode & 0o777 == 0o700
    assert len(recs[sub].calls) == 1


@pytest.mark.parametrize("sub", ["check", "status"])
def test_check_and_status_create_nothing(tmp_path, recs, sub):
    assert _main(sub, tmp_path) == 0
    assert not (tmp_path / "state").exists()


def test_run_dir_outside_state_dir_refused(tmp_path, recs, capsys):
    outside = tmp_path / "elsewhere" / "records"
    assert _main("plan", tmp_path, run_dir=str(outside)) == 64
    assert "run_dir" in capsys.readouterr().err
    assert not (tmp_path / "elsewhere").exists() and not recs["plan"].calls


def test_run_dir_dotdot_escape_refused(tmp_path, recs):
    sneaky = str(tmp_path / "state" / ".." / "elsewhere")
    assert _main("plan", tmp_path, run_dir=sneaky) == 64
    assert not (tmp_path / "elsewhere").exists()


def test_run_dir_symlink_refused(tmp_path, recs):
    (tmp_path / "state" / "r1").mkdir(parents=True)
    (tmp_path / "target").mkdir()
    (tmp_path / "state" / "r1" / "records").symlink_to(tmp_path / "target")
    assert _main("plan", tmp_path) == 64
    assert not recs["plan"].calls


def test_run_dir_symlinked_parent_refused(tmp_path, recs):
    (tmp_path / "state").mkdir()
    (tmp_path / "target").mkdir()
    (tmp_path / "state" / "r1").symlink_to(tmp_path / "target")
    assert _main("plan", tmp_path) == 64
    assert not (tmp_path / "target" / "records").exists()


def test_run_dir_regular_file_refused(tmp_path, recs):
    (tmp_path / "state" / "r1").mkdir(parents=True)
    (tmp_path / "state" / "r1" / "records").write_text("x")
    assert _main("plan", tmp_path) == 64


def test_existing_run_dir_reused_untouched(tmp_path, recs):
    rd = tmp_path / "state" / "r1" / "records"
    rd.mkdir(parents=True)
    rd.chmod(0o755)
    (rd / "keep").write_text("k")
    assert _main("plan", tmp_path) == 7
    assert (rd / "keep").read_text() == "k" and rd.stat().st_mode & 0o777 == 0o755


def test_create_run_tolerates_runner_made_parent(tmp_path, recs):
    from avocado_flash_remote import state

    assert _main("plan", tmp_path) == 7
    sd = tmp_path / "state"
    state.create_run(
        sd, run_id="r1", profile_hash="p", plan_hash="h", board_identity={}, image_roles=["a"], arm=False
    )
    assert (sd / "r1" / "state.json").is_file() and (sd / "r1" / "records").is_dir()


# --- required_stdlib (task 6.4) -------------------------------------------


def _independent_stdlib_walk(zf):
    found = set()
    for name in zf.namelist():
        if not name.endswith(".py"):
            continue
        tree = ast.parse(zf.read(name).decode())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                found.add(node.module.split(".")[0])
    return sorted(found - {bundle.PACKAGE})


def test_bundle_json_required_stdlib_matches_independent_walk(built):
    info, _ = built
    with zipfile.ZipFile(info.path) as z:
        meta = json.loads(z.read("BUNDLE.json"))
        expected = _independent_stdlib_walk(z)
    assert meta["required_stdlib"] == expected
    assert meta["required_stdlib"] == sorted(set(meta["required_stdlib"]))
    for must in ("hashlib", "json", "os", "sys", "zipfile"):
        assert must in meta["required_stdlib"]
    assert bundle.PACKAGE not in meta["required_stdlib"]
    assert all("." not in m for m in meta["required_stdlib"])


def test_required_stdlib_helper_counts_from_imports(tmp_path):
    (tmp_path / "m.py").write_text("from os import path\nimport a.b\nfrom . import x\nfrom avocado_flash_remote import y\n")
    src = (tmp_path / "m.py").read_bytes()
    assert bundle._stdlib_modules(src, "m.py") == ["a", "os"]


# ------------------------------------------------- record-set manifest (5.12)


def _plan_stub(tmp_path, code=0, write=True):
    def stub(*a, run_dir=None, **k):
        if write:
            from avocado_flash_remote import evidence

            evidence.write_record(
                run_dir,
                "plan.json",
                {
                    "run_id": "r1",
                    "board_identity": {"machine_id": "m1", "device_serial": "s1"},
                    "image_hashes": {"boot": "ab" * 32},
                },
            )
        return type("R", (), {"exit_code": code})()

    return stub


def _manifest(rd):
    return json.loads((rd / "MANIFEST.json").read_text())


def test_manifest_written_after_plan_and_verifies(tmp_path, monkeypatch):
    from avocado_flash_remote import evidence

    monkeypatch.setattr(runner, "run_plan", _plan_stub(tmp_path))
    assert _main("plan", tmp_path, tool_version="9.9") == 0
    rd = tmp_path / "state" / "r1" / "records"
    assert evidence.verify_record_set(rd).ok
    m = _manifest(rd)
    assert [a["name"] for a in m["artifacts"]] == ["plan.json"]
    assert m["host_tool_version"] == "9.9"
    assert m["runner_version"] == runner.RUNNER_VERSION
    assert m["run_status"] == "runner-complete"
    assert m["image_hashes"] == {"boot": "ab" * 32}
    assert m["board_identity"] == {"machine_id": "m1", "device_serial": "s1"}
    assert m["profile_hash"] == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert "MANIFEST.json" not in [a["name"] for a in m["artifacts"]]
    assert not [p for p in rd.iterdir() if p.name.endswith(".tmp")]


def test_manifest_defaults_and_incomplete_on_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "run_plan", _plan_stub(tmp_path, code=4, write=False))
    assert _main("plan", tmp_path) == 4
    m = _manifest(tmp_path / "state" / "r1" / "records")
    assert m["host_tool_version"] == "unknown"
    assert m["run_status"] == "incomplete"
    assert m["board_identity"] is None and m["image_hashes"] == {}


def test_manifest_for_refusal_without_records_lists_nothing_and_verifies(tmp_path, monkeypatch):
    from avocado_flash_remote import evidence

    monkeypatch.setattr(runner, "run_plan", _plan_stub(tmp_path, code=2, write=False))
    assert _main("plan", tmp_path) == 2
    rd = tmp_path / "state" / "r1" / "records"
    assert _manifest(rd)["artifacts"] == []
    assert evidence.verify_record_set(rd).ok


def test_manifest_on_unexpected_exception(tmp_path, monkeypatch):
    from avocado_flash_remote import evidence

    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(runner, "run_plan", boom)
    assert _main("plan", tmp_path) == 70
    rd = tmp_path / "state" / "r1" / "records"
    assert _manifest(rd)["run_status"] == "incomplete" and evidence.verify_record_set(rd).ok


def test_tampered_record_fails_verify(tmp_path, monkeypatch):
    from avocado_flash_remote import evidence

    monkeypatch.setattr(runner, "run_plan", _plan_stub(tmp_path))
    _main("plan", tmp_path)
    rd = tmp_path / "state" / "r1" / "records"
    (rd / "plan.json").write_text("{}")
    assert not evidence.verify_record_set(rd).ok


def test_rerun_rebuilds_manifest_without_stale_entries(tmp_path, monkeypatch):
    from avocado_flash_remote import evidence

    monkeypatch.setattr(runner, "run_plan", _plan_stub(tmp_path))
    _main("plan", tmp_path)
    rd = tmp_path / "state" / "r1" / "records"
    (rd / "extra.json").write_text("{}")
    _main("plan", tmp_path)
    assert [a["name"] for a in _manifest(rd)["artifacts"]] == ["extra.json", "plan.json"]
    (rd / "extra.json").unlink()
    _main("plan", tmp_path)
    assert [a["name"] for a in _manifest(rd)["artifacts"]] == ["plan.json"]
    assert evidence.verify_record_set(rd).ok


def test_manifest_takes_transition_log_from_state_file(tmp_path, monkeypatch):
    from avocado_flash_remote import state

    sd = tmp_path / "state"
    state.create_run(sd, run_id="r1", profile_hash="p", plan_hash="h", board_identity={"machine_id": "zz"}, image_roles=["a"], arm=False)
    monkeypatch.setattr(runner, "run_write", lambda *a, **k: type("R", (), {"exit_code": 0})())
    assert _main("write", tmp_path) == 0
    m = _manifest(sd / "r1" / "records")
    assert [t["phase"] for t in m["transition_log"]] == ["planned"]
    assert m["board_identity"] == {"machine_id": "zz"}


@pytest.mark.parametrize("sub", ["check", "status"])
def test_check_status_write_no_manifest(tmp_path, recs, sub):
    assert _main(sub, tmp_path) == 0
    assert not list(tmp_path.rglob("MANIFEST.json"))
