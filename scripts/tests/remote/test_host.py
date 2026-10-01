"""Host transport tests (task 6.1). Stub transport only: no ssh is ever run."""

from __future__ import annotations

import hashlib
import ast
import io
import json
import pathlib
import re
import shlex
import subprocess
import tarfile

import pytest

from avocado_flash_remote import bundle, evidence, host
from avocado_flash_remote.host import (
    HostError,
    RunResult,
    Secret,
    SshTransport,
    StubTransport,
)
from avocado_flash_remote.profile import load_profile_bytes

SHIPPED = pathlib.Path(host.__file__).resolve().parent / "profiles"
PASSWORD = "hunter2-Zq9!"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class FakeResolved:
    def __init__(self, data: bytes):
        self.data = data
        self.sha256 = _sha(data)
        self.profile = load_profile_bytes(data)
        self.rechecked = 0

    def recheck(self):
        self.rechecked += 1


@pytest.fixture
def resolved():
    return FakeResolved((SHIPPED / "fixture-none.json").read_bytes())


@pytest.fixture
def kit(tmp_path, resolved):
    images = tmp_path / "images"
    images.mkdir()
    files = {"boot.img": b"B" * 3000, "rootfs.img": b"R" * 5000}
    lines = []
    for name, data in files.items():
        (images / name).write_bytes(data)
        lines.append(f"{_sha(data)}  {name}\n")
    (images / "MANIFEST.hashes").write_text("".join(lines))
    (images / "NOTES.md").write_text("not staged")
    info = bundle.build_bundle(resolved.data, tmp_path / "b.pyz", "test-1")
    return images, info.path, files


def df_ok(avail_kib: int) -> RunResult:
    out = (
        "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
        f"tmpfs 999999 1 {avail_kib} 1% /run\n"
    )
    return RunResult(0, out.encode(), b"")


def handler_for(avail_kib: int):
    def h(argv, stdin, sudo):
        joined = " ".join(argv)
        if "df" in argv or "df -Pk" in joined:
            return df_ok(avail_kib)
        if argv[:2] == ["id", "-un"]:
            return RunResult(0, b"operator\n", b"")
        return RunResult(0, b"", b"")

    return h


# --- host pattern ---------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    ["-oProxyCommand=x", "", "a b", "a;b", "x@-y", "-x@host", "h$(id)", "a/b", "h\n", "u@@h"],
)
def test_host_pattern_rejects(bad):
    with pytest.raises(HostError):
        SshTransport(bad)


@pytest.mark.parametrize("good", ["board", "10.0.0.5", "root@my-board.local", "u_1@h_2"])
def test_host_pattern_accepts(good):
    assert SshTransport(good).host == good


# --- ssh command line (never executed) ------------------------------------


def test_command_line_shape():
    t = SshTransport("op@board", extra_opts=["-p", "2222"])
    cmd = t.command_line(["echo", "a b", "c;d"])
    assert cmd[0] == "ssh"
    assert "BatchMode=no" in cmd
    dd = cmd.index("--")
    assert cmd[dd + 1] == "op@board"
    assert len(cmd) == dd + 3
    assert shlex.split(cmd[dd + 2]) == ["echo", "a b", "c;d"]
    assert cmd[1:3] == ["-o", "BatchMode=no"]
    assert "-p" in cmd[:dd]


def test_batchmode_setting():
    cmd = SshTransport("h", batch_mode=True).command_line(["true"])
    assert "BatchMode=yes" in cmd


def test_sudo_wrapping_forms():
    t = SshTransport("h")
    remote, payload = t._wrap(["install", "-d", "/x"], None, True)
    assert remote == ["sudo", "-n", "install", "-d", "/x"]
    assert payload is None
    t.set_password(Secret(PASSWORD))
    remote, payload = t._wrap(["install", "-d", "/x"], b"data", True)
    assert remote == ["sudo", "-S", "-p", "", "install", "-d", "/x"]
    assert payload == PASSWORD.encode() + b"\n" + b"data"
    cmd = t.command_line(remote)
    assert shlex.split(cmd[-1])[:4] == ["sudo", "-S", "-p", ""]
    assert PASSWORD not in " ".join(cmd)
    # non-sudo calls never see the password
    remote, payload = t._wrap(["true"], b"x", False)
    assert payload == b"x"


def test_ssh_run_uses_own_session_and_files(monkeypatch, tmp_path):
    seen = {}

    class FakeStdin:
        def __init__(self):
            self.buf = b""

        def write(self, b):
            self.buf += b

        def close(self):
            pass

    class FakeProc:
        pid = 4242

        def __init__(self, cmd, **kw):
            seen["cmd"] = cmd
            seen["kw"] = kw
            self.stdin = kw["stdin"] if kw["stdin"] not in (subprocess.PIPE, subprocess.DEVNULL) else FakeStdin()
            seen["stdin"] = self.stdin
            kw["stdout"].write(b"out-bytes")
            kw["stdout"].flush()
            self.returncode = 0

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(subprocess, "Popen", FakeProc)
    t = SshTransport("h")
    t.set_password(Secret(PASSWORD))
    res = t.run(["true"], b"payload", sudo=True, timeout=5)
    assert res.rc == 0 and res.stdout == b"out-bytes"
    kw = seen["kw"]
    assert kw["start_new_session"] is True
    assert kw["stdout"] is not subprocess.PIPE and kw["stderr"] is not subprocess.PIPE
    assert PASSWORD not in " ".join(seen["cmd"])
    assert "env" not in kw or PASSWORD not in str(kw["env"])


# --- secret hygiene -------------------------------------------------------


def test_secret_hides():
    s = Secret(PASSWORD)
    assert PASSWORD not in repr(s) and PASSWORD not in str(s)
    assert PASSWORD not in f"{s!r} {s}"
    with pytest.raises(TypeError):
        import pickle

        pickle.dumps(s)


# --- sudo -----------------------------------------------------------------


def test_sudo_probe_both_ways():
    ok = StubTransport(handler=lambda a, s, u: RunResult(0, b"", b""))
    assert host.sudo_probe(ok) is True
    assert ok.calls[0].argv == ["sudo", "-n", "true"]
    bad = StubTransport(handler=lambda a, s, u: RunResult(1, b"", b"sudo: a password is required"))
    assert host.sudo_probe(bad) is False


def test_acquire_sudo_uses_noninteractive_when_possible():
    t = StubTransport(handler=lambda a, s, u: RunResult(0, b"", b""))
    asked = []
    host.acquire_sudo(t, ask_password=lambda: asked.append(1) or PASSWORD)
    assert asked == [] and t.sudo_password is None


def test_acquire_sudo_prompts_and_password_hygiene(tmp_path, kit, resolved, capsys):
    images, bundle_path, files = kit

    def h(argv, stdin, sudo):
        if argv == ["sudo", "-n", "true"]:
            return RunResult(1, b"", b"password required")
        if "df" in argv or any("df -Pk" in a for a in argv):
            return df_ok(10_000_000)
        if argv[:2] == ["id", "-un"]:
            return RunResult(0, b"operator\n", b"")
        return RunResult(0, b"", b"")

    t = StubTransport(handler=h)
    host.acquire_sudo(t, ask_password=lambda: PASSWORD)
    assert isinstance(t.sudo_password, Secret)
    host.stage(t, resolved.profile, resolved, images, bundle_path, dry_run=False)
    host.run_remote(t, "check", {"staging_dir": "/run/s", "state_dir": "/s"}, "/run/s/b.pyz")
    out = capsys.readouterr()
    blobs = [out.out, out.err]
    priv_stdin_hits = 0
    for c in t.calls:
        blobs.append(json.dumps(c.argv))
        blobs.append(repr(c))
        blobs.append(json.dumps(c.env))
        if c.stdin_bytes is not None and PASSWORD.encode() in c.stdin_bytes:
            assert c.sudo is True
            assert c.stdin_bytes.startswith(PASSWORD.encode() + b"\n")
            priv_stdin_hits += 1
    assert priv_stdin_hits >= 1
    for b in blobs:
        assert PASSWORD not in b
    assert PASSWORD not in repr(t) and PASSWORD not in str(t.__dict__.get("sudo_password"))
    # no written file under tmp_path holds it
    for p in tmp_path.rglob("*"):
        if p.is_file():
            assert PASSWORD.encode() not in p.read_bytes()
    # privileged calls use -S -p ''
    privileged = [c for c in t.calls if c.sudo]
    assert privileged and all(c.argv[:4] == ["sudo", "-S", "-p", ""] for c in privileged)


def test_failed_password_error_has_no_secret():
    def h(argv, stdin, sudo):
        if argv == ["sudo", "-n", "true"]:
            return RunResult(1, b"", b"")
        return RunResult(1, b"", b"Sorry, try again.")

    t = StubTransport(handler=h)
    with pytest.raises(HostError) as ei:
        host.acquire_sudo(t, ask_password=lambda: PASSWORD)
    assert PASSWORD not in str(ei.value) and PASSWORD not in repr(ei.value)


def test_no_tty_refuses(monkeypatch):
    t = StubTransport(handler=lambda a, s, u: RunResult(1, b"", b""))
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    with pytest.raises(HostError, match="terminal"):
        host.acquire_sudo(t)


# --- staging --------------------------------------------------------------


def test_dry_run_offline(kit, resolved, capsys):
    images, bundle_path, files = kit

    def poisoned(argv, stdin, sudo):
        raise AssertionError("dry-run must not touch the transport")

    t = StubTransport(handler=poisoned)
    host.stage(t, resolved.profile, resolved, images, bundle_path, dry_run=True)
    out = capsys.readouterr().out
    assert t.calls == []
    for name, data in files.items():
        assert name in out and _sha(data) in out and str(len(data)) in out
    assert "MANIFEST.hashes" in out
    assert bundle_path.name in out
    assert "NOTES.md" not in out
    assert out.rstrip().endswith("nothing was copied")


def test_dry_run_with_no_transport_at_all(kit, resolved, capsys):
    images, bundle_path, _ = kit
    host.stage(None, resolved.profile, resolved, images, bundle_path, dry_run=True)
    assert "nothing was copied" in capsys.readouterr().out


def test_dry_run_rejects_hash_mismatch(kit, resolved):
    images, bundle_path, _ = kit
    (images / "boot.img").write_bytes(b"tampered")
    with pytest.raises(HostError, match="boot.img"):
        host.stage(None, resolved.profile, resolved, images, bundle_path, dry_run=True)


def test_manifest_unsafe_name_rejected(kit, resolved):
    images, bundle_path, _ = kit
    (images / "MANIFEST.hashes").write_text(f"{'a'*64}  ../etc/passwd\n")
    with pytest.raises(HostError):
        host.stage(None, resolved.profile, resolved, images, bundle_path, dry_run=True)


def test_real_stage_call_order_and_modes(kit, resolved):
    images, bundle_path, files = kit
    t = StubTransport(handler=handler_for(10_000_000))
    host.stage(t, resolved.profile, resolved, images, bundle_path, dry_run=False)
    kinds = [c.kind for c in t.calls]
    # space check first, then user lookup / mkdir, then tar, then verification
    assert kinds[0] == "run" and ("df" in t.calls[0].argv or any("df" in a for a in t.calls[0].argv))
    assert not any(c.kind == "put_tar" for c in t.calls[:1])
    tar_i = kinds.index("put_tar")
    mk_i = next(i for i, c in enumerate(t.calls) if "install" in c.argv)
    assert 0 < mk_i < tar_i
    mk = t.calls[mk_i]
    assert mk.sudo is True
    assert "0755" in mk.argv and "-o" in mk.argv and "operator" in mk.argv
    assert resolved.profile.staging.dir in mk.argv
    tar = t.calls[tar_i]
    assert tar.dest_dir == resolved.profile.staging.dir
    names = set(tar.files)
    assert names == {"boot.img", "rootfs.img", "MANIFEST.hashes", "profile.json", bundle_path.name}
    assert tar.files["profile.json"] == resolved.data
    assert tar.modes[bundle_path.name] == 0o755
    for n in ("boot.img", "rootfs.img", "MANIFEST.hashes", "profile.json"):
        assert tar.modes[n] == 0o644
    after = t.calls[tar_i + 1 :]
    assert any("sha256sum" in " ".join(c.argv) and "--strict" in " ".join(c.argv) for c in after)
    assert resolved.rechecked >= 1


def test_insufficient_space_refuses_before_copy(kit, resolved):
    images, bundle_path, files = kit
    need = resolved.profile.staging.min_free_kib
    t = StubTransport(handler=handler_for(need))  # no room for the images
    with pytest.raises(HostError, match="space"):
        host.stage(t, resolved.profile, resolved, images, bundle_path, dry_run=False)
    assert not any(c.kind == "put_tar" for c in t.calls)
    assert not any("install" in c.argv for c in t.calls)


@pytest.mark.parametrize("garbage", [b"", b"nonsense", b"Filesystem a b c\nonly two\n", b"h\nx y z notanumber 1 /\n"])
def test_unparseable_df_refuses(kit, resolved, garbage):
    images, bundle_path, _ = kit
    t = StubTransport(handler=lambda a, s, u: RunResult(0, garbage, b""))
    with pytest.raises(HostError):
        host.stage(t, resolved.profile, resolved, images, bundle_path, dry_run=False)
    assert not any(c.kind == "put_tar" for c in t.calls)


def test_remote_verify_failure_refuses(kit, resolved):
    images, bundle_path, _ = kit
    base = handler_for(10_000_000)

    def h(argv, stdin, sudo):
        if "--strict" in " ".join(argv):
            return RunResult(1, b"boot.img: FAILED", b"")
        return base(argv, stdin, sudo)

    t = StubTransport(handler=h)
    with pytest.raises(HostError, match="verif"):
        host.stage(t, resolved.profile, resolved, images, bundle_path, dry_run=False)


# --- run / reconcile ------------------------------------------------------


def test_run_remote_writes_request_atomically_then_runs_bundle():
    t = StubTransport(handler=lambda a, s, u: RunResult(0, b"", b""))
    req = {"staging_dir": "/run/s", "state_dir": "/var/s", "run_id": "r1"}
    host.run_remote(t, "write", req, "/run/s/b.pyz")
    put, run = t.calls
    assert put.sudo is False
    assert json.loads(put.stdin_bytes) == req
    assert "mv" in " ".join(put.argv)
    assert run.sudo is True
    assert run.argv[:2] == ["sudo", "-n"]
    assert run.argv[2:4] == ["python3", "/run/s/b.pyz"]
    assert "--detach" in run.argv


def test_run_remote_check_has_no_detach():
    t = StubTransport(handler=lambda a, s, u: RunResult(0, b"", b""))
    host.run_remote(t, "check", {"staging_dir": "/run/s"}, "/run/s/b.pyz")
    assert "--detach" not in t.calls[-1].argv


def test_run_remote_unknown_subcommand():
    with pytest.raises(HostError):
        host.run_remote(StubTransport(), "rm-rf", {"staging_dir": "/x"}, "/x/b")


def test_reconcile_after_drop_reports_remote_phase():
    def h(argv, stdin, sudo):
        if "write" in argv:
            raise ConnectionResetError("ssh dropped")
        if "status" in argv:
            return RunResult(0, b"status: writing run=r1 recovery=wait\n", b"")
        return RunResult(0, b"", b"")

    t = StubTransport(handler=h)
    with pytest.raises(ConnectionResetError):
        host.run_remote(t, "write", {"staging_dir": "/run/s", "state_dir": "/var/s"}, "/run/s/b.pyz")
    rec = host.reconcile(t, "/var/s", "/run/s/b.pyz", "/run/s")
    assert rec.phase == "writing" and rec.run_id == "r1" and rec.recovery == "wait"
    # not complete without verified records
    v = evidence.VerifyResult(True)
    assert evidence.final_status(rec.phase, v) == "incomplete"


def test_reconcile_no_run_and_unreadable():
    def ok_status(a, s, u):
        return RunResult(0, b"status: no run recorded\n", b"") if "python3" in a else RunResult(0)

    def bad_status(a, s, u):
        return RunResult(1, b"status: state unreadable run=r9: bad\n", b"") if "python3" in a else RunResult(0)

    t = StubTransport(handler=ok_status)
    assert host.reconcile(t, "/s", "/b", "/st").phase is None
    t2 = StubTransport(handler=bad_status)
    r = host.reconcile(t2, "/s", "/b", "/st")
    assert r.phase is None and r.ok is False


# --- collect --------------------------------------------------------------


def _record_tar(tmp_path, tamper=False, drop_file=False, truncate=False):
    rd = evidence.new_run_dir(tmp_path / "remote")
    rs = evidence.RecordSet(
        rd, "1", "r1", "p" * 8, {"boot": "a" * 8}, {"s": "1"}, ["complete"],
        "2026-10-01T00:00:00Z", "2026-10-01T00:00:00Z",
    )
    rs.add("runner.log", b"log line\n" * 200)
    rs.add("plan.json", {"k": "v"})
    rs.finalize("runner-complete")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for p in sorted(rd.iterdir()):
            if drop_file and p.name == "plan.json":
                continue
            data = p.read_bytes()
            if tamper and p.name == "runner.log":
                data = b"X" * len(data)
            ti = tarfile.TarInfo(p.name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    raw = buf.getvalue()
    if truncate:
        raw = raw[:3000]  # inside runner.log, past the tar padding
    return raw


def test_collect_verified(tmp_path):
    raw = _record_tar(tmp_path)
    t = StubTransport(handler=lambda a, s, u: RunResult(0, raw, b""))
    dest = tmp_path / "local"
    v = host.collect(t, "r1", dest, remote_run_dir="/var/s/run-1")
    assert v.ok
    assert evidence.final_status("complete", v) == "complete"
    assert t.calls[0].sudo is True


@pytest.mark.parametrize("mode", ["truncate", "tamper", "drop_file"])
def test_collect_bad_fails(tmp_path, mode):
    raw = _record_tar(tmp_path, **{mode: True})
    t = StubTransport(handler=lambda a, s, u: RunResult(0, raw, b""))
    dest = tmp_path / "local"
    try:
        v = host.collect(t, "r1", dest, remote_run_dir="/var/s/run-1")
    except HostError:
        return  # truncated stream refused outright
    assert not v.ok
    assert evidence.final_status("complete", v) == "not-verified"


def test_collect_nonzero_rc_fails(tmp_path):
    t = StubTransport(handler=lambda a, s, u: RunResult(2, b"", b"tar: boom"))
    with pytest.raises(HostError):
        host.collect(t, "r1", tmp_path / "l", remote_run_dir="/x")


def test_collect_rejects_path_traversal(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        ti = tarfile.TarInfo("../evil")
        ti.size = 1
        tf.addfile(ti, io.BytesIO(b"x"))
    t = StubTransport(handler=lambda a, s, u: RunResult(0, buf.getvalue(), b""))
    with pytest.raises(HostError):
        host.collect(t, "r1", tmp_path / "l", remote_run_dir="/x")
    assert not (tmp_path / "evil").exists()


# --- root-direct privilege mode --------------------------------------------


def _id_handler(id_out: bytes, id_rc: int = 0):
    def h(argv, stdin, sudo):
        if argv == ["id", "-u"]:
            return RunResult(id_rc, id_out, b"")
        if argv[:2] == ["id", "-un"]:
            return RunResult(0, b"root\n", b"")
        if argv == ["sudo", "-n", "true"]:
            return RunResult(1, b"", b"sudo: not found")
        return RunResult(0, b"", b"")

    return h


def test_root_login_runs_without_sudo_and_never_prompts():
    t = StubTransport(handler=_id_handler(b"0\n"))
    asked = []
    mode = host.acquire_sudo(t, ask_password=lambda: asked.append(1) or PASSWORD)
    assert mode == host.PRIVILEGE_ROOT == "root (no sudo)"
    assert asked == [] and t.sudo_password is None
    res = t.run(["install", "-d", "/x"], None, sudo=True)
    assert res.rc == 0
    assert t.calls[-1].argv == ["install", "-d", "/x"]
    assert all("sudo" not in c.argv for c in t.calls)


def test_root_mode_applies_to_streamed_payloads_too():
    t = StubTransport(handler=_id_handler(b"0\n"))
    host.acquire_sudo(t, ask_password=lambda: PASSWORD)
    t.run(["tee", "/x"], b"body", sudo=True)
    assert t.calls[-1].argv == ["tee", "/x"] and t.calls[-1].stdin_bytes == b"body"


def test_non_root_keeps_sudo_probe_then_prompt():
    seen = []

    def h(argv, stdin, sudo):
        seen.append(list(argv))
        if argv == ["id", "-u"]:
            return RunResult(0, b"1000\n", b"")
        if argv == ["sudo", "-n", "true"]:
            return RunResult(1, b"", b"password required")
        return RunResult(0, b"", b"")

    t = StubTransport(handler=h)
    mode = host.acquire_sudo(t, ask_password=lambda: PASSWORD)
    assert mode == host.PRIVILEGE_SUDO_PASSWORD
    assert seen.index(["id", "-u"]) < seen.index(["sudo", "-n", "true"])
    assert isinstance(t.sudo_password, Secret)


def test_non_root_without_password_need_reports_sudo_mode():
    def h(argv, stdin, sudo):
        if argv == ["id", "-u"]:
            return RunResult(0, b"1000\n", b"")
        return RunResult(0, b"", b"")

    t = StubTransport(handler=h)
    assert host.acquire_sudo(t, ask_password=lambda: PASSWORD) == host.PRIVILEGE_SUDO_NOPASS
    assert t.calls[-1].argv == ["sudo", "-n", "true"]


@pytest.mark.parametrize("garbage", [b"uid=0(root)\n", b"root\n", b"0 1\n", b"-0\n", b"0x0\n"])
def test_unparseable_id_refuses_closed(garbage):
    t = StubTransport(handler=_id_handler(garbage))
    with pytest.raises(HostError, match="privilege"):
        host.acquire_sudo(t, ask_password=lambda: PASSWORD)
    assert not host_is_root(t)


def host_is_root(t) -> bool:
    return getattr(t, "root_direct", False)


@pytest.mark.parametrize("rc,out", [(127, b""), (1, b"0\n"), (0, b"")])
def test_unanswerable_id_falls_through_to_sudo_never_root(rc, out):
    t = StubTransport(handler=_id_handler(out, rc))
    # sudo -n true fails in this handler and the password is supplied
    def h(argv, stdin, sudo):
        if argv == ["id", "-u"]:
            return RunResult(rc, out, b"")
        if argv == ["sudo", "-n", "true"]:
            return RunResult(1, b"", b"")
        return RunResult(0, b"", b"")

    t = StubTransport(handler=h)
    assert host.acquire_sudo(t, ask_password=lambda: PASSWORD) == host.PRIVILEGE_SUDO_PASSWORD
    assert not host_is_root(t)


def test_reacquire_resets_root_mode():
    t = StubTransport(handler=_id_handler(b"0\n"))
    host.acquire_sudo(t)
    assert t.root_direct is True
    t.handler = lambda a, s, u: RunResult(0, b"1000\n", b"") if a == ["id", "-u"] else RunResult(0, b"", b"")
    host.acquire_sudo(t)
    assert t.root_direct is False


# --- remote interpreter (task 6.4) ----------------------------------------

MISSING_ON_TARGET = "hashlib _hashlib _sha2 json tempfile datetime socket getpass base64 random uuid secrets".split()


def probe_handler(missing=(), rc=0, version="3.12.1"):
    """A board whose interpreter lacks `missing` (names it was asked about)."""

    def h(argv, stdin, sudo):
        if len(argv) >= 3 and argv[1] == "-c":
            if rc != 0:
                return RunResult(rc, b"", b"sh: not found")
            asked = set(re.findall(r"'([A-Za-z0-9_]+)'", argv[2]))
            gone = sorted(asked & set(missing))
            out = ("MISSING " + " ".join(gone)) if gone else f"OK {version}"
            return RunResult(0, (out + "\n").encode(), b"")
        return RunResult(0, b"", b"")

    return h


@pytest.mark.parametrize("bad", ["-oFoo", "a b", "../x", "x/../y", "$(x)", "", "a;b", "-", "a\nb"])
def test_validate_remote_python_rejects_hostile(bad):
    with pytest.raises(HostError):
        host.validate_remote_python(bad)


@pytest.mark.parametrize("good", ["python3", "/usr/bin/python3", "/opt/py-3.12/bin/python3.12", "python3+x", "./py"])
def test_validate_remote_python_accepts(good):
    assert host.validate_remote_python(good) == good


def test_probe_ok_returns_version_and_runs_list_form():
    t = StubTransport(handler=probe_handler())
    ver = host.probe_interpreter(t, "/opt/py/bin/python3", ["hashlib", "json", "sys"])
    assert ver == "3.12.1"
    (c,) = t.calls
    assert c.argv[:2] == ["/opt/py/bin/python3", "-c"] and len(c.argv) == 3
    assert c.sudo is False
    assert "hashlib" in c.argv[2]


def test_probe_missing_modules_refuses_naming_them():
    t = StubTransport(handler=probe_handler(missing=MISSING_ON_TARGET))
    mods = ["argparse", "hashlib", "json", "zipfile", "base64", "random"]
    with pytest.raises(HostError) as ei:
        host.probe_interpreter(t, "python3", mods)
    msg = str(ei.value)
    for name in ("hashlib", "json", "base64", "random"):
        assert name in msg
    assert "zipfile" not in msg
    assert "python3" in msg and "--remote-python" in msg


def test_probe_interpreter_not_found():
    t = StubTransport(handler=probe_handler(rc=127))
    with pytest.raises(HostError) as ei:
        host.probe_interpreter(t, "/nope/python", ["sys"])
    assert "not found" in str(ei.value) and "/nope/python" in str(ei.value) and "--remote-python" in str(ei.value)


def test_probe_garbled_output_refuses():
    t = StubTransport(handler=lambda a, s, u: RunResult(0, b"banana\n", b""))
    with pytest.raises(HostError):
        host.probe_interpreter(t, "python3", ["sys"])


def test_probe_code_needs_only_sys_and_builtins():
    t = StubTransport(handler=probe_handler())
    host.probe_interpreter(t, "python3", ["json"])
    code = t.calls[0].argv[2]
    tree = ast.parse(code)
    imported = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert all(a.name == "sys" for n in imported if isinstance(n, ast.Import) for a in n.names)
    assert not [n for n in imported if isinstance(n, ast.ImportFrom)]


def test_run_remote_and_reconcile_use_given_interpreter():
    t = StubTransport(handler=lambda a, s, u: RunResult(0, b"status: no run recorded\n", b""))
    host.run_remote(t, "check", {"staging_dir": "/run/s"}, "/run/s/b.pyz", python="/opt/p/python3")
    assert t.calls[-1].argv[2:4] == ["/opt/p/python3", "/run/s/b.pyz"]
    host.reconcile(t, "/s", "/run/s/b.pyz", "/run/s", python="/opt/p/python3")
    assert t.calls[-1].argv[2:4] == ["/opt/p/python3", "/run/s/b.pyz"]


def test_stage_verifies_bundle_with_given_interpreter(kit, resolved):
    images, bundle_path, files = kit
    t = StubTransport(handler=handler_for(10_000_000))
    host.stage(t, resolved.profile, resolved, images, bundle_path, dry_run=False, python="/opt/p/python3")
    py = [c for c in t.calls if c.kind == "run" and c.argv and c.argv[0] == "/opt/p/python3"]
    assert len(py) == 1 and bundle_path.name in py[0].argv[-1]
