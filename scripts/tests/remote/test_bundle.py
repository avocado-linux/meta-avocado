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
NONCE_A = "a1" * 8
NONCE_B = "b2" * 8


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
        "invocation_nonce": NONCE_A,
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
    # The request's run_id now reaches run_status (the host asks for its own run); it was dropped before.
    assert args == (str(tmp_path / "state"),) and kw == {"run_id": "r1"}


def test_status_wiring_without_a_run_id_asks_for_the_current_run(tmp_path, recs):
    info = _archive_for_runner(tmp_path)
    req = _request(tmp_path)
    data = json.loads(req.read_text())
    del data["run_id"]
    req.write_text(json.dumps(data))
    assert runner.main(["status", "--request", str(req)], archive=info.path) == 0
    (args, kw), = recs["status"].calls
    assert kw == {"run_id": None}


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


def test_detach_writes_accepted_marker_before_the_subcommand_runs(tmp_path):
    info = _archive_for_runner(tmp_path)
    run_dir = tmp_path / "state" / "r1" / "records"
    seen = tmp_path / "seen.json"
    req = _request(tmp_path)
    driver = tmp_path / "driver.py"
    driver.write_text(
        textwrap.dedent(
            f"""
            import json, os, sys, dataclasses
            sys.path.insert(0, {str(PKG.parent)!r})
            from avocado_flash_remote import runner

            def stub(*a, **k):
                m = os.path.join({str(run_dir)!r}, "accepted")
                body = open(m).read() if os.path.exists(m) else None
                json.dump({{"body": body, "pid": os.getpid(), "tmp": os.path.exists(m + ".tmp")}}, open({str(seen)!r}, "w"))
                return type("R", (), {{"exit_code": 0}})()

            _real = runner.load_profile_bytes
            runner.load_profile_bytes = lambda b: dataclasses.replace(_real(b), state_dir={str(tmp_path / "state")!r})
            runner.run_write = stub
            sys.exit(runner.main(["write", "--request", {str(req)!r}, "--detach"], archive={str(info.path)!r}))
            """
        )
    )
    rc, out, err = _run([sys.executable, str(driver)], tmp_path, "d", timeout=20)
    assert rc == 0, err
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not seen.exists():
        time.sleep(0.05)
    m = json.loads(seen.read_text())
    assert m["body"] == f"{m['pid']}\nnonce={NONCE_A}\n"
    assert m["tmp"] is False


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


def test_manifest_is_built_from_the_runs_own_state_after_another_run_moves_current(tmp_path, monkeypatch):
    from avocado_flash_remote import state

    sd = tmp_path / "state"
    state.create_run(sd, run_id="r1", profile_hash="p", plan_hash="h", board_identity={"machine_id": "zz"}, image_roles=["a"], arm=False)
    state.create_run(sd, run_id="r2", profile_hash="p", plan_hash="h", board_identity={"machine_id": "other"}, image_roles=["a"], arm=False)
    assert (sd / "current").read_text().strip() == "r2"  # a later run took the pointer before r1 finished
    monkeypatch.setattr(runner, "run_write", lambda *a, **k: type("R", (), {"exit_code": 0})())
    assert _main("write", tmp_path) == 0  # the request names run r1
    m = _manifest(sd / "r1" / "records")
    assert [t["phase"] for t in m["transition_log"]] == ["planned"]
    assert m["board_identity"] == {"machine_id": "zz"}


@pytest.mark.parametrize("sub", ["check", "status"])
def test_check_status_write_no_manifest(tmp_path, recs, sub):
    assert _main(sub, tmp_path) == 0
    assert not list(tmp_path.rglob("MANIFEST.json"))


# ------------------------------------------- refused write leaves a finished run alone (5.16)


def _finished_run(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "run_plan", _plan_stub(tmp_path))
    assert _main("plan", tmp_path) == 0
    rd = tmp_path / "state" / "r1" / "records"
    assert _manifest(rd)["run_status"] == "runner-complete"
    return rd


def test_write_refused_before_any_work_leaves_a_finished_manifest_alone(tmp_path, monkeypatch):
    from avocado_flash_remote import evidence

    rd = _finished_run(tmp_path, monkeypatch)
    before = (rd / "MANIFEST.json").read_bytes()
    refused = type("R", (), {"exit_code": 1, "final_phase": None})()
    monkeypatch.setattr(runner, "run_write", lambda *a, **k: refused)
    assert _main("write", tmp_path) == 1
    assert (rd / "MANIFEST.json").read_bytes() == before
    assert evidence.verify_record_set(rd).ok


def test_write_that_did_work_and_failed_still_marks_the_manifest_incomplete(tmp_path, monkeypatch):
    rd = _finished_run(tmp_path, monkeypatch)
    failed = type("R", (), {"exit_code": 1, "final_phase": "failed"})()
    monkeypatch.setattr(runner, "run_write", lambda *a, **k: failed)
    assert _main("write", tmp_path) == 1
    assert _manifest(rd)["run_status"] == "incomplete"


def test_write_refused_without_a_prior_manifest_still_writes_an_incomplete_one(tmp_path, monkeypatch):
    refused = type("R", (), {"exit_code": 1, "final_phase": None})()
    monkeypatch.setattr(runner, "run_write", lambda *a, **k: refused)
    (tmp_path / "plan.json").write_text("{}")
    assert _main("write", tmp_path) == 1
    assert _manifest(tmp_path / "state" / "r1" / "records")["run_status"] == "incomplete"


def _finished_run_dir(tmp_path):
    from avocado_flash_remote import evidence

    run_dir = tmp_path / "state" / "r1" / "records"
    run_dir.mkdir(parents=True)
    rs = evidence.RecordSet(run_dir, "t", "1", "p" * 64, {}, {}, [], "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
    rs.add("write.json", {"ok": True})
    rs.add("runner.log", b"first run\n")
    rs.finalize("runner-complete")
    return run_dir


def test_detached_replay_of_a_written_run_is_refused_before_the_fork(tmp_path, monkeypatch, capsys):
    from avocado_flash_remote import evidence, state

    run_dir = _finished_run_dir(tmp_path)
    state.create_run(tmp_path / "state", run_id="r1", profile_hash="p", plan_hash="h", board_identity={}, image_roles=["a"], arm=False)
    before = {p.name: p.read_bytes() for p in run_dir.iterdir()}
    forks = []
    monkeypatch.setattr(runner.os, "fork", lambda: forks.append(1) or 0)
    monkeypatch.setattr(runner, "run_write", lambda *a, **k: pytest.fail("a replay must not reach the write"))
    info = _archive_for_runner(tmp_path)
    rc = runner.main(["write", "--request", str(_request(tmp_path)), "--detach"], archive=info.path)
    cap = capsys.readouterr()
    assert rc == 1
    assert forks == []
    assert "already has a state record" in cap.err and "nothing was written to the board" not in cap.err
    assert "detached:" not in cap.out
    assert {p.name: p.read_bytes() for p in run_dir.iterdir()} == before
    assert not list((tmp_path / "state" / "r1").glob("refused-*.log"))
    assert evidence.verify_record_set(run_dir).ok


def test_detached_write_whose_write_json_exists_without_state_is_also_refused(tmp_path, monkeypatch, capsys):
    run_dir = _finished_run_dir(tmp_path)
    monkeypatch.setattr(runner.os, "fork", lambda: pytest.fail("must refuse before forking"))
    info = _archive_for_runner(tmp_path)
    rc = runner.main(["write", "--request", str(_request(tmp_path)), "--detach"], archive=info.path)
    assert rc == 1
    assert "write refused" in capsys.readouterr().err
    assert (run_dir / "write.json").is_file()


_OUTCOME_DRIVER = """
import dataclasses, os, sys
sys.path.insert(0, {pkg!r})
from avocado_flash_remote import runner

def stub(*a, **k):
    rd = {run_dir!r}
    seen = {{n: os.path.exists(os.path.join(rd, n)) for n in ("outcome",)}}
    with open(os.path.join({tmp!r}, "seen.txt"), "w") as f:
        f.write(repr(seen) + " " + open(os.path.join(rd, "accepted")).read())
    {body}

_real = runner.load_profile_bytes
runner.load_profile_bytes = lambda b: dataclasses.replace(_real(b), state_dir={state!r})
runner.run_write = stub
sys.exit(runner.main(["write", "--request", {req!r}, "--detach"], archive={archive!r}))
"""


def _detached_write(tmp_path, body, *, pre=None):
    info = _archive_for_runner(tmp_path)
    run_dir = tmp_path / "state" / "r1" / "records"
    if pre:
        run_dir.mkdir(parents=True)
        for name, text in pre.items():
            (run_dir / name).write_text(text)
    req = _request(tmp_path)
    driver = tmp_path / "driver.py"
    driver.write_text(
        _OUTCOME_DRIVER.format(
            pkg=str(PKG.parent), run_dir=str(run_dir), tmp=str(tmp_path), body=body,
            state=str(tmp_path / "state"), req=str(req), archive=str(info.path),
        )
    )
    rc, out, err = _run([sys.executable, str(driver)], tmp_path, "d", timeout=20)
    assert rc == 0, err
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not (run_dir / "MANIFEST.json").exists():
        time.sleep(0.05)
    assert (run_dir / "MANIFEST.json").exists(), "the detached runner never finished"
    return run_dir


def test_detached_refused_write_leaves_a_refused_outcome_with_the_reason(tmp_path):
    body = (
        'R = type("R", (), {"exit_code": 1, "final_phase": None, "lines": '
        '["write refused: BootOrder changed since the plan", "nothing was written to the board"]})()\n'
        "    return R"
    )
    rd = _detached_write(tmp_path, body)
    assert (rd / "outcome").read_text() == (
        f"refused\nrun=r1\nnonce={NONCE_A}\nwrite refused: BootOrder changed since the plan\nnothing was written to the board\n"
    )


def test_detached_write_that_did_work_leaves_a_finished_outcome(tmp_path):
    body = 'return type("R", (), {"exit_code": 0, "final_phase": "complete", "lines": []})()'
    rd = _detached_write(tmp_path, body)
    assert (rd / "outcome").read_text() == f"finished\nrun=r1\nnonce={NONCE_A}\n"


def test_detached_write_that_failed_after_work_is_finished_not_refused(tmp_path):
    body = 'return type("R", (), {"exit_code": 1, "final_phase": "failed", "lines": ["write FAILED"]})()'
    rd = _detached_write(tmp_path, body)
    assert (rd / "outcome").read_text() == f"finished\nrun=r1\nnonce={NONCE_A}\n"


def test_detached_runner_that_crashes_leaves_no_outcome(tmp_path):
    rd = _detached_write(tmp_path, 'raise RuntimeError("kaput")')
    assert not (rd / "outcome").exists()
    assert "kaput" in (rd / "runner.log").read_text()


def test_every_invocation_rewrites_the_marker_set_and_drops_a_stale_outcome(tmp_path):
    pre = {"accepted": "99999\n", "outcome": "refused\nrun=r1\nwrite refused: an old attempt\n"}
    body = 'return type("R", (), {"exit_code": 0, "final_phase": "complete", "lines": []})()'
    rd = _detached_write(tmp_path, body, pre=pre)
    seen = (tmp_path / "seen.txt").read_text()
    assert seen.startswith("{'outcome': False}"), seen  # the old verdict was gone before the new run began
    pid = seen.split("}", 1)[1].split()[0]
    assert pid.isdigit() and pid != "99999"
    assert (rd / "accepted").read_text() == f"{pid}\nnonce={NONCE_A}\n"


# ------------------------------------------- 5.21: a second invocation of a running run


_HOLDER_DRIVER = """
import dataclasses, os, sys, time
sys.path.insert(0, {pkg!r})
from avocado_flash_remote import runner

def stub(*a, **k):
    while not os.path.exists({release!r}):
        time.sleep(0.02)
    return type("R", (), {{"exit_code": 0, "final_phase": "complete", "lines": []}})()

_real = runner.load_profile_bytes
runner.load_profile_bytes = lambda b: dataclasses.replace(_real(b), state_dir={state!r})
runner.run_write = stub
sys.exit(runner.main(["write", "--request", {req!r}, "--detach"], archive={archive!r}))
"""


def _start_holder(tmp_path):
    """Detach a first runner that stays inside its write until the test releases it."""
    info = _archive_for_runner(tmp_path)
    run_dir = tmp_path / "state" / "r1" / "records"
    release = tmp_path / "release"
    req = _request(tmp_path)
    driver = tmp_path / "holder.py"
    driver.write_text(
        _HOLDER_DRIVER.format(
            pkg=str(PKG.parent), release=str(release), state=str(tmp_path / "state"),
            req=str(req), archive=str(info.path),
        )
    )
    rc, _out, err = _run([sys.executable, str(driver)], tmp_path, "holder", timeout=20)
    assert rc == 0, err
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not (run_dir / "accepted").exists():
        time.sleep(0.02)
    assert (run_dir / "accepted").exists(), "the first runner never accepted"
    return info, run_dir, release


def _release_and_wait(run_dir, release):
    release.write_text("go")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not (run_dir / "MANIFEST.json").exists():
        time.sleep(0.02)
    assert (run_dir / "MANIFEST.json").exists(), "the first runner never finished"


def _snapshot(run_dir):
    return {p.name: p.read_bytes() for p in sorted(run_dir.iterdir())}


def _second_invocation(tmp_path, monkeypatch, info, nonce):
    state = tmp_path / "state"
    real = runner.load_profile_bytes
    monkeypatch.setattr(runner, "load_profile_bytes", lambda b: dataclasses.replace(real(b), state_dir=str(state)))
    monkeypatch.setattr(runner.os, "fork", lambda: pytest.fail("a refused second invocation must not fork"))
    monkeypatch.setattr(runner, "run_write", lambda *a, **k: pytest.fail("must not reach the write"))
    req = _request(tmp_path, invocation_nonce=nonce)
    return runner.main(["write", "--request", str(req), "--detach"], archive=info.path)


def test_a_symlinked_invocation_lock_path_is_refused_without_following_it(tmp_path, monkeypatch, capsys):
    state = tmp_path / "state"
    state.mkdir()
    victim = tmp_path / "victim"
    victim.write_text("keep")
    (state / ".invocation-r1.lock").symlink_to(victim)
    forks = []
    monkeypatch.setattr(runner.os, "fork", lambda: forks.append(1) or 0)
    monkeypatch.setattr(runner, "run_write", lambda *a, **k: pytest.fail("must not reach the write"))
    real = runner.load_profile_bytes
    monkeypatch.setattr(runner, "load_profile_bytes", lambda b: dataclasses.replace(real(b), state_dir=str(state)))
    info = _archive_for_runner(tmp_path)
    rc = runner.main(["write", "--request", str(_request(tmp_path, invocation_nonce=NONCE_A)), "--detach"], archive=info.path)
    cap = capsys.readouterr()
    assert rc == 1 and forks == []
    assert "invocation lock" in cap.err and "refused" in cap.err
    assert victim.read_text() == "keep"
    assert "detached:" not in cap.out


def test_second_invocation_while_the_first_runs_touches_nothing_of_the_first(tmp_path, monkeypatch, capsys):
    info, run_dir, release = _start_holder(tmp_path)
    before = _snapshot(run_dir)
    assert before["accepted"].decode().endswith(f"nonce={NONCE_A}\n")
    capsys.readouterr()
    rc = _second_invocation(tmp_path, monkeypatch, info, NONCE_B)
    cap = capsys.readouterr()
    after = _snapshot(run_dir)
    try:
        assert rc == 1
        assert after == before, "the second invocation changed the running runner's records"
        assert "outcome" not in after and "MANIFEST.json" not in after
        assert "already in progress" in cap.err
        # The board IS changing: the refusal must never tell the host nothing changed.
        text = (cap.out + cap.err).lower()
        assert "nothing was written" not in text and "changed nothing" not in text
        assert "detached:" not in cap.out
    finally:
        _release_and_wait(run_dir, release)
    # The first runner finished as itself: its verdict names its own nonce and its manifest is whole.
    assert (run_dir / "outcome").read_text() == f"finished\nrun=r1\nnonce={NONCE_A}\n"
    assert (run_dir / "accepted").read_text().endswith(f"nonce={NONCE_A}\n")
    from avocado_flash_remote import evidence

    assert json.loads((run_dir / "MANIFEST.json").read_text())["run_status"] == "runner-complete"
    assert evidence.verify_record_set(run_dir).ok


def test_second_invocation_does_not_write_a_refused_outcome_even_when_the_first_has_no_state_yet(tmp_path, monkeypatch):
    info, run_dir, release = _start_holder(tmp_path)
    assert not (tmp_path / "state" / "r1" / "state.json").exists()  # still hashing/checking: no state record
    try:
        assert _second_invocation(tmp_path, monkeypatch, info, NONCE_B) == 1
        assert not (run_dir / "outcome").exists()
    finally:
        _release_and_wait(run_dir, release)


def test_after_the_first_runner_is_gone_a_new_invocation_takes_over(tmp_path):
    # A crashed runner releases its lock with its process: the next invocation is not locked out.
    pre = {"accepted": "99999\nnonce=" + NONCE_B + "\n"}
    body = 'return type("R", (), {"exit_code": 0, "final_phase": "complete", "lines": []})()'
    rd = _detached_write(tmp_path, body, pre=pre)
    assert (rd / "outcome").read_text() == f"finished\nrun=r1\nnonce={NONCE_A}\n"


@pytest.mark.parametrize("bad", [None, "", "xyz", "A" * 16, "a" * 7, "a" * 65, 12345])
def test_detached_write_without_a_valid_nonce_is_refused_before_the_fork(tmp_path, monkeypatch, capsys, bad):
    info = _archive_for_runner(tmp_path)
    real = runner.load_profile_bytes
    monkeypatch.setattr(runner, "load_profile_bytes", lambda b: dataclasses.replace(real(b), state_dir=str(tmp_path / "state")))
    monkeypatch.setattr(runner.os, "fork", lambda: pytest.fail("must refuse before forking"))
    req = _request(tmp_path)
    data = json.loads(req.read_text())
    if bad is None:
        del data["invocation_nonce"]
    else:
        data["invocation_nonce"] = bad
    req.write_text(json.dumps(data))
    rc = runner.main(["write", "--request", str(req), "--detach"], archive=info.path)
    assert rc != 0
    assert "invocation_nonce" in capsys.readouterr().err
    assert not (tmp_path / "state" / "r1" / "records" / "accepted").exists()
