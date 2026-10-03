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
from avocado_flash_remote.profile import READBACK_RUN_BASE, STAGING_MARKER, load_profile_bytes

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


def _is_tool_probe(argv) -> bool:
    argv = list(argv)
    if argv[:2] == ["sudo", "-n"]:  # the probe runs as root, on the runner's own tool path
        argv = argv[2:]
    elif argv[:4] == ["sudo", "-S", "-p", ""]:
        argv = argv[4:]
    return argv[:2] == ["sh", "-c"] and "--version" in argv[2] and "sha256sum" in argv[2]


def _is_dir_probe(argv) -> bool:
    argv = list(argv)
    if argv[:2] == ["sudo", "-n"]:  # the probe is privileged
        argv = argv[2:]
    return argv[:2] == ["sh", "-c"] and "stat -c" in argv[2]


def handler_for(avail_kib: int, missing_tools=(), dir_answer=b"ABSENT\n", dir_rc=0):
    def h(argv, stdin, sudo):
        joined = " ".join(argv)
        if _is_tool_probe(argv):
            if missing_tools:
                return RunResult(0, ("MISSING " + " ".join(missing_tools) + "\n").encode(), b"")
            return RunResult(0, b"OK\n", b"")
        if host._ALIAS_PROBE in argv:  # the state and readback paths carry no symlink
            return RunResult(0, b"PLAIN\n" * (len(argv) - argv.index(host._ALIAS_PROBE) - 2), b"")
        if _is_dir_probe(argv):
            return RunResult(dir_rc, dir_answer, b"")
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
    # SSH transport sudo password setter, not a Django account password; never stored.
    # nosemgrep: python.django.security.audit.unvalidated-password.unvalidated-password
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
    # SSH transport sudo password setter, not a Django account password; never stored.
    # nosemgrep: python.django.security.audit.unvalidated-password.unvalidated-password
    t.set_password(Secret(PASSWORD))
    res = t.run(["true"], b"payload", sudo=True, timeout=5)
    assert res.rc == 0 and res.stdout == b"out-bytes"
    kw = seen["kw"]
    assert kw["start_new_session"] is True
    assert kw["stdout"] is not subprocess.PIPE and kw["stderr"] is not subprocess.PIPE
    assert PASSWORD not in " ".join(seen["cmd"])
    assert "env" not in kw or PASSWORD not in str(kw["env"])


def test_ssh_run_terminates_the_ssh_child_when_the_wait_is_interrupted(monkeypatch):
    from avocado_flash_remote import host as hostmod

    terminated = []

    class FakeProc:
        pid = 4243

        def __init__(self, cmd, **kw):
            self.stdin = None

        def wait(self, timeout=None):
            raise KeyboardInterrupt

    monkeypatch.setattr(subprocess, "Popen", FakeProc)
    monkeypatch.setattr(hostmod, "_terminate", lambda proc: terminated.append(proc))
    with pytest.raises(KeyboardInterrupt):
        SshTransport("h").run(["true"], None, timeout=5)
    assert len(terminated) == 1 and terminated[0].pid == 4243


# --- secret hygiene -------------------------------------------------------


def test_secret_hides():
    s = Secret(PASSWORD)
    assert PASSWORD not in repr(s) and PASSWORD not in str(s)
    assert PASSWORD not in f"{s!r} {s}"
    with pytest.raises(TypeError):
        import pickle

        # The test asserts Secret refuses pickling; nothing is unpickled.
        # nosemgrep: python.lang.security.deserialization.pickle.avoid-pickle
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
        if _is_tool_probe(argv):
            return RunResult(0, b"OK\n", b"")
        if host._ALIAS_PROBE in argv:
            return RunResult(0, b"PLAIN\n" * (len(argv) - argv.index(host._ALIAS_PROBE) - 2), b"")
        if any("stat -c" in a for a in argv):  # the staging-directory probe, sudo-prefixed in password mode
            return RunResult(0, b"ABSENT\n", b"")
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
    # board-tool probe first, then the space check, then user lookup / mkdir, then tar, then verification
    assert _is_tool_probe(t.calls[0].argv)
    assert kinds[1] == "run" and ("df" in t.calls[1].argv or any("df" in a for a in t.calls[1].argv))
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
    assert names == {"boot.img", "rootfs.img", "MANIFEST.hashes", "profile.json", STAGING_MARKER, bundle_path.name}
    assert tar.files["profile.json"] == resolved.data
    assert tar.modes[bundle_path.name] == 0o755
    for n in ("boot.img", "rootfs.img", "MANIFEST.hashes", "profile.json", STAGING_MARKER):
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
    req = {"staging_dir": "/run/s", "state_dir": "/var/s", "run_id": "r1", "invocation_nonce": "ab" * 8}
    host.run_remote(t, "write", req, "/run/s/b.pyz")
    put, run, rm = t.calls
    assert put.sudo is False
    assert json.loads(put.stdin_bytes) == req
    assert "mv" in " ".join(put.argv)
    assert run.sudo is True
    assert run.argv[:2] == ["sudo", "-n"]
    assert run.argv[2:4] == ["python3", "/run/s/b.pyz"]
    assert "--detach" in run.argv
    # The host removes the request it wrote once the runner call returned (the runner has read it by then).
    assert rm.argv == ["rm", "-f", "--", put.argv[-1]] and rm.sudo is False


def test_the_request_file_and_its_temp_name_carry_the_invocation_nonce():
    t = StubTransport(handler=lambda a, s, u: RunResult(0, b"", b""))
    host.run_remote(t, "write", {"staging_dir": "/run/s", "invocation_nonce": "ab" * 8}, "/run/s/b.pyz")
    put = t.calls[0]
    path = put.argv[-1]
    assert path == "/run/s/request-write-" + "ab" * 8 + ".json"
    assert '"$1.tmp"' in put.argv[2]  # the temp file is derived from the same name


def test_two_invocations_never_share_a_request_path_and_each_removes_only_its_own():
    t1 = StubTransport(handler=lambda a, s, u: RunResult(0, b"", b""))
    t2 = StubTransport(handler=lambda a, s, u: RunResult(0, b"", b""))
    for t, nonce in ((t1, "aa" * 8), (t2, "bb" * 8)):
        host.run_remote(t, "write", {"staging_dir": "/run/s", "invocation_nonce": nonce}, "/run/s/b.pyz")
    p1, p2 = t1.calls[0].argv[-1], t2.calls[0].argv[-1]
    assert p1 != p2
    assert t1.calls[-1].argv[-1] == p1 and t2.calls[-1].argv[-1] == p2


def test_a_request_without_a_nonce_still_gets_a_unique_path():
    paths = []
    for _ in range(2):
        t = StubTransport(handler=lambda a, s, u: RunResult(0, b"", b""))
        host.run_remote(t, "check", {"staging_dir": "/run/s"}, "/run/s/b.pyz")
        paths.append(t.calls[0].argv[-1])
    assert paths[0] != paths[1]
    assert all(p.startswith("/run/s/request-check-") and p.endswith(".json") for p in paths)


def test_the_request_is_removed_even_when_the_runner_call_raises():
    def handler(argv, stdin, sudo):
        if "python3" in argv:
            raise host.HostTimeout("timed out")
        return RunResult(0, b"", b"")

    t = StubTransport(handler=handler)
    with pytest.raises(host.HostTimeout):
        host.run_remote(t, "check", {"staging_dir": "/run/s"}, "/run/s/b.pyz")
    assert t.calls[-1].argv[:2] == ["rm", "-f"]


def test_a_failed_request_removal_is_not_an_error():
    def handler(argv, stdin, sudo):
        return RunResult(1) if argv[0] == "rm" else RunResult(0, b"ok", b"")

    res = host.run_remote(StubTransport(handler=handler), "check", {"staging_dir": "/run/s"}, "/run/s/b.pyz")
    assert res.rc == 0


def test_run_remote_check_has_no_detach():
    t = StubTransport(handler=lambda a, s, u: RunResult(0, b"", b""))
    host.run_remote(t, "check", {"staging_dir": "/run/s"}, "/run/s/b.pyz")
    assert "--detach" not in t.calls[-2].argv and "b.pyz" in " ".join(t.calls[-2].argv)


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


def test_reconcile_asks_for_the_hosts_own_run_when_given_a_run_id():
    t = StubTransport(handler=lambda a, s, u: RunResult(0, b"status: complete run=rA recovery=none\n", b""))
    rec = host.reconcile(t, "/s", "/run/s/b.pyz", "/run/s", run_id="rA")
    put = next(c for c in t.calls if c.argv[:2] == ["sh", "-c"] and "request-status" in c.argv[-1])
    assert json.loads(put.stdin_bytes)["run_id"] == "rA"
    assert (rec.ok, rec.phase, rec.run_id) == (True, "complete", "rA")


def test_reconcile_without_a_run_id_sends_none():
    t = StubTransport(handler=lambda a, s, u: RunResult(0, b"status: no run recorded\n", b""))
    host.reconcile(t, "/s", "/run/s/b.pyz", "/run/s")
    put = next(c for c in t.calls if c.argv[:2] == ["sh", "-c"] and "request-status" in c.argv[-1])
    assert "run_id" not in json.loads(put.stdin_bytes)


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


def _is_exists_probe(argv) -> bool:
    argv = list(argv)
    if argv[:2] == ["sudo", "-n"]:
        argv = argv[2:]
    return argv[:2] == ["sh", "-c"] and "command -v" in argv[2]


def probe_handler(missing=(), rc=0, version="3.12.1", present=True):
    """A board whose interpreter lacks `missing` (names it was asked about).

    ``present=False`` is an interpreter that is not installed: the existence probe answers its own exit code
    and a direct sudo exec answers what sudo does for a missing command (exit 1, not 127).
    """

    def h(argv, stdin, sudo):
        argv = list(argv)
        if _is_exists_probe(argv):
            return RunResult(0 if present else 127)
        if argv[:2] == ["sudo", "-n"]:  # the probe runs the way the runner does: privileged
            argv = argv[2:]
        if len(argv) >= 3 and argv[1] == "-c":
            if not present:
                return RunResult(1, b"", f"sudo: {argv[0]}: command not found".encode())
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
    exists, c = t.calls
    # Existence first, as root like the runner, because sudo exits 1 (not 127) for a missing command.
    assert _is_exists_probe(exists.argv) and exists.sudo is True and exists.argv[-1] == "/opt/py/bin/python3"
    # 5.41: privileged, like the runner, so "remote python" is the interpreter that runs it.
    assert c.argv[:4] == ["sudo", "-n", "/opt/py/bin/python3", "-c"] and len(c.argv) == 5
    assert c.sudo is True
    assert "hashlib" in c.argv[4]


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
    # What sudo returns for a missing command: exit 1 and its own words, never 127.
    t = StubTransport(handler=probe_handler(present=False))
    with pytest.raises(HostError) as ei:
        host.probe_interpreter(t, "/nope/python", ["sys"])
    assert "interpreter not found" in str(ei.value) and "/nope/python" in str(ei.value) and "--remote-python" in str(ei.value)


def test_a_failing_interpreter_that_exists_is_not_reported_as_missing():
    t = StubTransport(handler=probe_handler(rc=1))
    with pytest.raises(HostError) as ei:
        host.probe_interpreter(t, "python3", ["sys"])
    assert "failed on the board" in str(ei.value) and "not found" not in str(ei.value)


def test_the_stage_zip_check_reports_a_missing_interpreter_not_an_unopenable_bundle(kit, resolved):
    inner = handler_for(10_000_000)

    def h(argv, stdin, sudo):
        if _is_exists_probe(argv):
            return RunResult(127)
        if any("zipfile" in a for a in argv):
            return RunResult(1, b"", b"sudo: python3: command not found")
        return inner(argv, stdin, sudo)

    t, go = _stage(kit, resolved, h)
    with pytest.raises(HostError) as ei:
        go()
    assert "interpreter not found" in str(ei.value) and "cannot open the staged bundle" not in str(ei.value)


def test_probe_garbled_output_refuses():
    t = StubTransport(handler=lambda a, s, u: RunResult(0, b"banana\n", b""))
    with pytest.raises(HostError):
        host.probe_interpreter(t, "python3", ["sys"])


def test_probe_code_needs_only_sys_and_builtins():
    t = StubTransport(handler=probe_handler())
    host.probe_interpreter(t, "python3", ["json"])
    code = t.calls[0].argv[-1]
    tree = ast.parse(code)
    imported = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert all(a.name == "sys" for n in imported if isinstance(n, ast.Import) for a in n.names)
    assert not [n for n in imported if isinstance(n, ast.ImportFrom)]


def test_run_remote_and_reconcile_use_given_interpreter():
    t = StubTransport(handler=lambda a, s, u: RunResult(0, b"status: no run recorded\n", b""))
    host.run_remote(t, "check", {"staging_dir": "/run/s"}, "/run/s/b.pyz", python="/opt/p/python3")
    # The request removal now follows the runner call, so the runner call is the one before it.
    assert t.calls[-2].argv[2:4] == ["/opt/p/python3", "/run/s/b.pyz"]
    host.reconcile(t, "/s", "/run/s/b.pyz", "/run/s", python="/opt/p/python3")
    assert t.calls[-2].argv[2:4] == ["/opt/p/python3", "/run/s/b.pyz"]


def test_stage_verifies_bundle_with_given_interpreter(kit, resolved):
    images, bundle_path, files = kit
    t = StubTransport(handler=handler_for(10_000_000))
    host.stage(t, resolved.profile, resolved, images, bundle_path, dry_run=False, python="/opt/p/python3")
    py = [c for c in t.calls if c.kind == "run" and "/opt/p/python3" in c.argv[:3]]
    assert len(py) == 1 and bundle_path.name in py[0].argv[-1]


# --- 5.14 / 5.19 / 5.21: has the detached runner accepted the write ----------

RUN_DIR = "/var/lib/x/r1/records"
NONCE = "c3" * 8
OTHER_NONCE = "d4" * 8
SUDO_FAIL = b"sudo: a password is required"
ABSENT = RunResult(3)  # the marker probe's own exit code for "no such file": no words involved


def _unwrapped(handler):
    def unwrapped(argv, stdin, sudo):
        argv = list(argv)
        if argv[:2] == ["sudo", "-n"]:
            argv = argv[2:]
        return handler(argv, stdin, sudo)

    return unwrapped


def _is_read(argv, name):
    return argv[0] == "sh" and "exit 3" in argv[2] and argv[-1] == f"{RUN_DIR}/{name}"


def _presence(handler, calls=None):
    t = StubTransport(_unwrapped(handler))
    out = host.runner_presence(t, RUN_DIR)
    if calls is not None:
        calls.extend(t.calls)
    return out


def _proc_answer(word: bytes):
    return RunResult(0, word + b"\n")


def _accepted(pid=b"4242", nonce=NONCE):
    return RunResult(0, pid + b"\nnonce=" + nonce.encode() + b"\n")


def test_runner_presence_absent_without_marker():
    assert _presence(lambda a, s, u: ABSENT) == "absent"


def test_runner_presence_alive_when_pid_visible():
    def h(argv, stdin, sudo):
        if _is_read(argv, "accepted"):
            return _accepted()
        assert "/proc/" in " ".join(argv) and argv[-1] == "4242"
        return _proc_answer(b"alive")

    assert _presence(h) == "alive"


def test_runner_presence_exited_when_pid_gone():
    def h(argv, stdin, sudo):
        if _is_read(argv, "accepted"):
            return _accepted()
        return _proc_answer(b"gone")

    assert _presence(h) == "exited"


def test_runner_presence_unknown_for_unparsable_marker_or_transport_error():
    assert _presence(lambda a, s, u: RunResult(0, b"garbage\n")) == "unknown"
    assert _presence(lambda a, s, u: RunResult(0, b"")) == "unknown"

    def boom(a, s, u):
        raise host.HostError("reset")

    assert _presence(boom) == "unknown"


@pytest.mark.parametrize(
    "res",
    [
        RunResult(255, b"", b"ssh: connection reset"),
        RunResult(1, b"", SUDO_FAIL),
        RunResult(2, b"", b"cat: read error"),
        RunResult(1, b"", b"cat: /x: No such file or directory"),  # words never decide: only the exit code does
    ],
)
def test_marker_read_failure_other_than_not_found_is_unknown_not_absent(res):
    assert _presence(lambda a, s, u: res) == "unknown"


@pytest.mark.parametrize(
    "res",
    [
        RunResult(255, b"", b"ssh: connection reset"),
        RunResult(1, b"", SUDO_FAIL),
        RunResult(0, b"", b""),
        RunResult(0, b"maybe\n", b""),
    ],
)
def test_proc_probe_failure_is_unknown_not_exited(res):
    def h(argv, stdin, sudo):
        if _is_read(argv, "accepted"):
            return _accepted()
        return res

    assert _presence(h) == "unknown"


def test_proc_probe_runs_with_the_privilege_of_the_marker_read():
    calls = []

    def h(argv, stdin, sudo):
        if _is_read(argv, "accepted"):
            return _accepted()
        return _proc_answer(b"alive")

    _presence(h, calls)
    assert len(calls) == 2
    assert all(c.sudo for c in calls), [(c.argv, c.sudo) for c in calls]


# --- 5.21: a localised board must not change a verdict -----------------------


class _LocalShell:
    """Runs the host's argv for real, under a given locale, against a local directory."""

    def __init__(self, env_extra):
        self.env_extra = env_extra
        self.calls = []

    def run(self, argv, stdin, *, sudo=False, timeout=60):
        argv = list(argv)
        if argv[:2] == ["sudo", "-n"]:
            argv = argv[2:]
        self.calls.append(argv)
        env = {"PATH": "/usr/bin:/bin", **self.env_extra}
        p = subprocess.run(argv, input=stdin, capture_output=True, env=env, timeout=30)
        return RunResult(p.returncode, p.stdout, p.stderr)


@pytest.mark.parametrize("loc", ["C", "de_DE.UTF-8", "fr_FR.UTF-8", "ja_JP.UTF-8", "xx_YY.invalid"])
def test_absent_marker_is_absent_under_any_locale_with_the_real_shell(tmp_path, loc):
    t = _LocalShell({"LANG": loc, "LC_ALL": loc, "LANGUAGE": loc.split(".")[0]})
    run_dir = tmp_path / "records"
    run_dir.mkdir()
    assert host.runner_presence(t, str(run_dir)) == "absent"
    assert host.runner_outcome(t, str(run_dir), "r1", NONCE) == ("none", "")
    assert host.invocation_owner(t, str(run_dir), "r1", NONCE) == "none"


def test_present_marker_is_read_by_the_real_shell(tmp_path):
    t = _LocalShell({})
    run_dir = tmp_path / "records"
    run_dir.mkdir()
    (run_dir / "outcome").write_text(f"finished\nrun=r1\nnonce={NONCE}\n")
    assert host.runner_outcome(t, str(run_dir), "r1", NONCE) == ("finished", "")


def test_a_localised_no_such_file_words_with_a_nonabsent_code_never_decide():
    # The same German words a localised cat prints, but the exit code is not the probe's "absent" code.
    de = b"cat: /x: Datei oder Verzeichnis nicht gefunden"
    assert _presence(lambda a, s, u: RunResult(1, b"", de)) == "unknown"
    assert host.runner_outcome(StubTransport(_unwrapped(lambda a, s, u: RunResult(1, b"", de))), RUN_DIR, "r1", NONCE)[0] == "unknown"


# --- 5.19 / 5.21: the runner's outcome marker --------------------------------


def _outcome(handler, nonce=NONCE):
    return host.runner_outcome(StubTransport(_unwrapped(handler)), RUN_DIR, "r1", nonce)


def test_outcome_refused_carries_the_reason_verbatim():
    body = f"refused\nrun=r1\nnonce={NONCE}\nwrite refused: BootOrder changed\nnothing was written to the board\n".encode()
    kind, text = _outcome(lambda a, s, u: RunResult(0, body))
    assert kind == "refused"
    assert text == "write refused: BootOrder changed\nnothing was written to the board"


def test_outcome_finished():
    assert _outcome(lambda a, s, u: RunResult(0, f"finished\nrun=r1\nnonce={NONCE}\n".encode())) == ("finished", "")


def test_outcome_missing_file_is_none():
    assert _outcome(lambda a, s, u: ABSENT)[0] == "none"


def test_outcome_from_another_run_is_not_trusted():
    kind, _ = _outcome(lambda a, s, u: RunResult(0, f"refused\nrun=OTHER\nnonce={NONCE}\nwrite refused: x\n".encode()))
    assert kind == "unknown"


@pytest.mark.parametrize("kind", ["refused", "finished"])
def test_outcome_from_another_invocation_is_not_trusted(kind):
    body = f"{kind}\nrun=r1\nnonce={OTHER_NONCE}\nwrite refused: x\n".encode()
    assert _outcome(lambda a, s, u: RunResult(0, body))[0] == "unknown"


def test_outcome_without_a_nonce_line_is_not_trusted():
    assert _outcome(lambda a, s, u: RunResult(0, b"finished\nrun=r1\n"))[0] == "unknown"


@pytest.mark.parametrize(
    "res",
    [
        RunResult(255, b"", b"ssh: connection reset"),
        RunResult(1, b"", SUDO_FAIL),
        RunResult(0, b"", b""),
        RunResult(0, f"weird\nrun=r1\nnonce={NONCE}\n".encode(), b""),
    ],
)
def test_outcome_unreadable_or_unrecognised_is_unknown(res):
    assert _outcome(lambda a, s, u: res)[0] == "unknown"


def test_outcome_transport_error_is_unknown():
    def boom(a, s, u):
        raise host.HostError("reset")

    assert _outcome(boom)[0] == "unknown"


# --- 5.21: whose runner is it -------------------------------------------------


def _owner(handler, nonce=NONCE):
    return host.invocation_owner(StubTransport(_unwrapped(handler)), RUN_DIR, "r1", nonce)


def test_owner_is_ours_when_the_accepted_marker_carries_our_nonce():
    assert _owner(lambda a, s, u: _accepted() if _is_read(a, "accepted") else ABSENT) == "ours"


def test_owner_is_other_when_the_accepted_marker_carries_another_nonce():
    assert _owner(lambda a, s, u: _accepted(nonce=OTHER_NONCE)) == "other"


def test_owner_is_none_when_no_runner_accepted_anything():
    assert _owner(lambda a, s, u: ABSENT) == "none"


@pytest.mark.parametrize(
    "res",
    [
        RunResult(0, b"4242\n"),  # a marker without a nonce line
        RunResult(0, b"4242\nnonce=\n"),
        RunResult(0, b""),
        RunResult(255, b"", b"ssh: connection reset"),
        RunResult(1, b"", SUDO_FAIL),
    ],
)
def test_owner_unreadable_or_without_a_nonce_is_unknown(res):
    assert _owner(lambda a, s, u: res) == "unknown"


def test_owner_transport_error_is_unknown():
    def boom(a, s, u):
        raise host.HostError("reset")

    assert _owner(boom) == "unknown"


def test_owner_is_other_when_our_nonce_is_recorded_as_refused():
    def h(argv, stdin, sudo):
        if _is_read(argv, "accepted"):
            return _accepted()
        return RunResult(0, f"refused\nrun=r1\nnonce={NONCE}\nwhy\n".encode())

    assert _owner(h) == "other"


def test_owner_with_an_unreadable_outcome_is_unknown_not_ours():
    def h(argv, stdin, sudo):
        if _is_read(argv, "accepted"):
            return _accepted()
        return RunResult(1, b"", SUDO_FAIL)

    assert _owner(h) == "unknown"


def test_owner_with_a_finished_outcome_is_ours():
    def h(argv, stdin, sudo):
        if _is_read(argv, "accepted"):
            return _accepted()
        return RunResult(0, f"finished\nrun=r1\nnonce={NONCE}\n".encode())

    assert _owner(h) == "ours"


def test_the_dead_refusal_log_probe_is_gone():
    assert not hasattr(host, "refusal_newer_than_manifest")
    assert not hasattr(host, "_REFUSAL_PROBE")
    assert not hasattr(host, "_no_such_file")


def test_a_failed_request_put_removes_the_half_written_temp_file_too():
    def handler(argv, stdin, sudo):
        return RunResult(1, b"", b"No space left") if argv[0] == "sh" else RunResult(0, b"", b"")

    t = StubTransport(handler=handler)
    with pytest.raises(host.HostError, match="cannot write the request"):
        host.run_remote(t, "check", {"staging_dir": "/run/s"}, "/run/s/b.pyz")
    put, rm = t.calls
    path = put.argv[-1]
    assert rm.argv == ["rm", "-f", "--", path, path + ".tmp"]


def test_remote_df_runs_under_the_c_locale():
    from types import SimpleNamespace as NS

    seen = []

    class T:
        def run(self, argv, stdin, sudo=False, timeout=None):
            seen.append(argv)
            return NS(rc=0, out="Filesystem 1K-blocks Used Available Use% Mounted on\ntmpfs 100 1 99999 1% /x\n")

    host.check_staging_space(T(), NS(staging=NS(dir="/x", min_free_kib=1)))
    assert "LC_ALL=C df -Pk" in " ".join(seen[0])


def test_collected_files_are_written_through_an_owner_only_atomic_path(tmp_path):
    raw = _record_tar(tmp_path)
    t = StubTransport(handler=lambda a, s, u: RunResult(0, raw, b""))
    dest = tmp_path / "local"
    assert host.collect(t, "r1", dest, remote_run_dir="/var/s/run-1").ok
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in dest.iterdir())
    assert not [p for p in dest.iterdir() if p.name.endswith(".tmp")]


def test_a_failure_while_writing_an_extracted_file_leaves_no_partial_file(tmp_path, monkeypatch):
    raw = _record_tar(tmp_path)
    t = StubTransport(handler=lambda a, s, u: RunResult(0, raw, b""))
    dest = tmp_path / "local"

    def boom(*a, **k):
        raise OSError("rename failed")

    monkeypatch.setattr(evidence.os, "rename", boom)
    with pytest.raises(OSError):
        host.collect(t, "r1", dest, remote_run_dir="/var/s/run-1")
    assert list(dest.iterdir()) == []


# --- board prerequisites at stage (task 5.37) ------------------------------


@pytest.mark.parametrize("missing", [("install",), ("sha256sum",), ("dd",), ("install", "sha256sum", "dd")])
def test_stage_refuses_a_board_missing_gnu_tools_naming_them_before_any_write(kit, resolved, missing):
    images, bundle_path, _ = kit
    t = StubTransport(handler=handler_for(10_000_000, missing_tools=missing))
    with pytest.raises(HostError) as ei:
        host.stage(t, resolved.profile, resolved, images, bundle_path, dry_run=False)
    msg = str(ei.value)
    assert all(name in msg for name in missing), msg
    assert "busybox" in msg.lower() or "GNU" in msg
    assert not any(c.kind == "put_tar" for c in t.calls)
    assert not any("install" in c.argv for c in t.calls)
    # Only the read-only tool probe itself runs as root before the refusal.
    assert [c for c in t.calls if c.sudo] == [t.calls[0]]


def test_stage_tool_probe_is_the_first_remote_call_and_runs_as_root_on_the_runners_tool_path(kit, resolved):
    images, bundle_path, _ = kit
    t = StubTransport(handler=handler_for(10_000_000))
    host.stage(t, resolved.profile, resolved, images, bundle_path, dry_run=False)
    first = t.calls[0]
    assert _is_tool_probe(first.argv) and first.sudo is True
    # The runner searches only DEFAULT_TOOL_DIRS, so the probe must resolve the tools the same way as root.
    assert first.argv[:3] == ["sudo", "-n", "sh"] and first.argv[-1] == "/usr/sbin:/usr/bin:/sbin:/bin"
    script = first.argv[4]
    for tool in ("install", "sha256sum", "dd"):
        assert f"{tool}" in script
    for verb in ("-d ", "of=", "rm ", "mv ", "chmod"):
        assert verb not in script


@pytest.mark.parametrize("garbage", [b"", b"banana\n"])
def test_stage_refuses_when_the_tool_probe_answer_is_unintelligible(kit, resolved, garbage):
    images, bundle_path, _ = kit

    def h(argv, stdin, sudo):
        if _is_tool_probe(argv):
            return RunResult(0, garbage, b"")
        return handler_for(10_000_000)(argv, stdin, sudo)

    t = StubTransport(handler=h)
    with pytest.raises(HostError):
        host.stage(t, resolved.profile, resolved, images, bundle_path, dry_run=False)
    assert not any(c.kind == "put_tar" for c in t.calls)


# --- the tool probe matches GNU coreutils positively (task 5.42) ------------


def _make_tools(directory, banners):
    directory.mkdir()
    for tool, banner in banners.items():
        if banner is not None:
            p = directory / tool
            p.write_text(f"#!/bin/sh\necho '{banner}'\n")  # builtins only: PATH holds just these directories
            p.chmod(0o755)
    return directory


def _run_probe_script(tmp_path, banners, login_banners=None):
    """Run the real probe shell text. ``banners`` (tool -> text or None for absent) are the tools on the path
    handed to the probe; ``login_banners`` are tools on the login PATH the process inherits."""
    bindir = _make_tools(tmp_path / "probe-bin", banners)
    login = _make_tools(tmp_path / "login-bin", login_banners or {})
    done = subprocess.run(["/bin/sh", "-c", host._TOOL_PROBE, "sh", str(bindir)], capture_output=True, text=True,
                          env={"PATH": str(login)}, check=False)  # fmt: skip
    return done.stdout.strip().splitlines()[-1]


def test_a_gnu_tool_on_the_login_path_does_not_mask_a_busybox_one_on_the_system_path(tmp_path):
    busybox = "BusyBox v1.36.1 multi-call binary."
    got = _run_probe_script(
        tmp_path, {**GNU_BANNERS, "dd": busybox}, login_banners={"dd": "dd (coreutils) 9.4"}
    )
    assert got == "MISSING dd"


def test_a_tool_only_on_the_login_path_is_not_found(tmp_path):
    assert _run_probe_script(tmp_path, {**GNU_BANNERS, "install": None}, login_banners={"install": "install (GNU coreutils) 9.4"}) == "MISSING install"


GNU_BANNERS = {t: f"{t} (GNU coreutils) 9.4" for t in ("install", "sha256sum", "dd")}


def test_probe_accepts_gnu_coreutils_banners(tmp_path):
    assert _run_probe_script(tmp_path, GNU_BANNERS) == "OK"


def test_probe_accepts_the_dd_banner_that_omits_the_word_gnu(tmp_path):
    # GNU dd prints "dd (coreutils) 9.x"; refusing it would refuse every real GNU board.
    assert _run_probe_script(tmp_path, {**GNU_BANNERS, "dd": "dd (coreutils) 9.12"}) == "OK"


@pytest.mark.parametrize(
    "banner",
    ["install (uutils coreutils) 0.0.27", "toybox 0.8.11", "install (GNU findutils) 4.9", "no banner here"],
    ids=["uutils", "toybox", "gnu-not-coreutils", "unrecognised"],
)
def test_probe_names_a_tool_whose_banner_is_not_gnu_coreutils(tmp_path, banner):
    got = _run_probe_script(tmp_path, {**GNU_BANNERS, "install": banner})
    assert got == "MISSING install"


def test_probe_still_names_a_busybox_tool_and_an_absent_tool(tmp_path):
    got = _run_probe_script(tmp_path, {**GNU_BANNERS, "dd": "BusyBox v1.36.1 multi-call binary.", "sha256sum": None})
    assert got == "MISSING sha256sum dd"


def test_refusal_text_says_which_userlands_are_refused():
    t = StubTransport(handler=handler_for(10_000_000, missing_tools=("install",)))
    with pytest.raises(HostError) as ei:
        host.probe_board_tools(t)
    msg = str(ei.value)
    assert "GNU coreutils" in msg and "install" in msg
    assert all(word in msg.lower() for word in ("busybox", "toybox", "uutils")), msg


def test_stage_dry_run_still_opens_no_connection_with_the_probe_added(kit, resolved):
    images, bundle_path, _ = kit
    host.stage(None, resolved.profile, resolved, images, bundle_path, dry_run=True)


# --- 5.41: stage's directory, its checksum listing and the interpreter it checks with -----------


def _stage(kit, resolved, handler):
    images, bundle_path, _ = kit
    t = StubTransport(handler=handler)
    return t, lambda: host.stage(t, resolved.profile, resolved, images, bundle_path, dry_run=False)


def test_stage_creates_the_directory_only_when_it_is_absent_and_looks_first_as_root(kit, resolved):
    t, go = _stage(kit, resolved, handler_for(10_000_000, dir_answer=b"ABSENT\n"))
    go()
    probe_i = next(i for i, c in enumerate(t.calls) if _is_dir_probe(c.argv))
    mk_i = next(i for i, c in enumerate(t.calls) if "install" in c.argv)
    assert probe_i < mk_i
    probe = t.calls[probe_i]
    # Root's own view: a parent the SSH user cannot search must not read as "absent".
    assert probe.sudo is True
    assert probe.argv[-2:] == [resolved.profile.staging.dir, STAGING_MARKER]


def test_stage_leaves_an_existing_directory_owned_by_the_ssh_user_as_it_is(kit, resolved):
    t, go = _stage(kit, resolved, handler_for(10_000_000, dir_answer=b"OWNER operator 755 MARKED\n"))
    go()
    assert not any("install" in c.argv for c in t.calls)
    assert not any("chmod" in c.argv for c in t.calls)
    assert any(c.kind == "put_tar" for c in t.calls)


@pytest.mark.parametrize("mode", [b"777", b"775", b"757", b"1777", b"2775", b"770"], ids=lambda m: m.decode())
def test_stage_tightens_a_group_or_other_writable_directory_the_ssh_user_owns_without_privilege(kit, resolved, mode):
    t, go = _stage(kit, resolved, handler_for(10_000_000, dir_answer=b"OWNER operator " + mode + b" MARKED\n"))
    go()
    (chmod,) = [c for c in t.calls if "chmod" in c.argv]
    assert chmod.argv == ["chmod", "0755", resolved.profile.staging.dir] and chmod.sudo is False
    first_copy = next(i for i, c in enumerate(t.calls) if c.kind == "put_tar")
    assert t.calls.index(chmod) < first_copy


@pytest.mark.parametrize("mode", [b"755", b"750", b"700", b"0755"], ids=lambda m: m.decode())
def test_stage_accepts_a_directory_nobody_else_can_write_and_does_not_chmod_it(kit, resolved, mode):
    t, go = _stage(kit, resolved, handler_for(10_000_000, dir_answer=b"OWNER operator " + mode + b" MARKED\n"))
    go()
    assert not any("chmod" in c.argv for c in t.calls)


def test_stage_refuses_when_the_tightening_chmod_fails(kit, resolved):
    inner = handler_for(10_000_000, dir_answer=b"OWNER operator 777 MARKED\n")

    def h(argv, stdin, sudo):
        if "chmod" in argv:
            return RunResult(1, b"", b"Operation not permitted")
        return inner(argv, stdin, sudo)

    t, go = _stage(kit, resolved, h)
    with pytest.raises(HostError, match="staging directory"):
        go()
    assert not any(c.kind == "put_tar" for c in t.calls)


def test_stage_never_chmods_a_directory_another_user_owns_even_when_it_is_writable(kit, resolved):
    t, go = _stage(kit, resolved, handler_for(10_000_000, dir_answer=b"OWNER root 777 MARKED\n"))
    with pytest.raises(HostError, match="staging directory"):
        go()
    assert not any("chmod" in c.argv for c in t.calls)


def _real_probe(path, marker=STAGING_MARKER):
    done = subprocess.run(
        ["/bin/sh", "-c", host._DIR_PROBE, "sh", str(path), marker], capture_output=True, text=True, check=True
    )
    return done.stdout.split()


def test_the_directory_probe_prints_owner_mode_and_marker_state_under_the_real_shell(tmp_path):
    d = tmp_path.resolve() / "staging"
    d.mkdir()
    d.chmod(0o775)
    owner = _real_probe(d)
    assert owner[0] == "OWNER" and owner[2] == "775" and owner[3] == "UNMARKED" and len(owner) == 4
    (d / STAGING_MARKER).write_text("x")
    assert _real_probe(d)[3] == "MARKED"


def test_the_directory_probe_does_not_count_a_marker_that_is_not_a_regular_file(tmp_path):
    d = tmp_path.resolve() / "staging"
    d.mkdir()
    (d / STAGING_MARKER).symlink_to("/etc/hostname")
    assert _real_probe(d)[3] == "UNMARKED"


def test_the_directory_probe_reports_absent_for_a_missing_path_under_a_plain_parent(tmp_path):
    assert _real_probe(tmp_path.resolve() / "nope") == ["ABSENT"]


@pytest.mark.parametrize("existing", [True, False], ids=["existing-dir", "absent-dir"])
def test_the_directory_probe_refuses_a_path_reached_through_a_symlinked_parent(tmp_path, existing):
    real = tmp_path.resolve() / "real"
    real.mkdir()
    if existing:
        (real / "stage").mkdir()
        (real / "stage" / STAGING_MARKER).write_text("x")
    link = tmp_path.resolve() / "link"
    link.symlink_to(real)
    assert _real_probe(link / "stage") == ["SYMLINK"]


@pytest.mark.parametrize(
    "answer",
    [
        b"OWNER root 755 MARKED\n", b"OWNER UNKNOWN 755 MARKED\n", b"SYMLINK\n", b"NOTDIR\n", b"", b"banana\n",
        b"OWNER operator extra MARKED\n", b"OWNER operator\n", b"OWNER operator 7x5 MARKED\n",
        b"OWNER operator 755 MARKED extra\n", b"OWNER operator 755\n", b"OWNER operator 755 MAYBE\n",
    ],
    ids=[
        "other-owner", "no-such-uid", "symlink", "not-a-directory", "empty", "garbage",
        "extra-fields", "no-mode", "bad-mode", "too-many-fields", "old-three-word-form", "unknown-marker-word",
    ],
)
def test_stage_refuses_a_staging_directory_the_ssh_user_does_not_own_and_changes_nothing(kit, resolved, answer):
    t, go = _stage(kit, resolved, handler_for(10_000_000, dir_answer=answer))
    with pytest.raises(HostError, match="staging directory"):
        go()
    assert not any("install" in c.argv for c in t.calls)
    assert not any(c.kind == "put_tar" for c in t.calls)


def test_stage_refuses_an_existing_directory_without_the_marker_even_when_the_ssh_user_owns_it(kit, resolved):
    t, go = _stage(kit, resolved, handler_for(10_000_000, dir_answer=b"OWNER operator 755 UNMARKED\n"))
    with pytest.raises(HostError, match="no .* marker"):
        go()
    assert not any(c.kind == "put_tar" for c in t.calls)
    assert not any("chmod" in c.argv or "install" in c.argv for c in t.calls)


@pytest.mark.parametrize("answer", [b"OWNER root 755 UNMARKED\n", b"OWNER root 700 UNMARKED\n"], ids=["var-log-like", "tight"])
def test_a_root_login_never_gets_a_marker_written_into_an_existing_system_directory(kit, resolved, answer):
    inner = handler_for(10_000_000, dir_answer=answer)

    def h(argv, stdin, sudo):
        if argv[:2] == ["id", "-un"]:
            return RunResult(0, b"root\n", b"")
        return inner(argv, stdin, sudo)

    t, go = _stage(kit, resolved, h)
    with pytest.raises(HostError, match="no .* marker"):
        go()
    assert not any(c.kind == "put_tar" for c in t.calls)


def test_stage_accepts_an_existing_directory_that_an_earlier_stage_marked_for_a_root_login(kit, resolved):
    inner = handler_for(10_000_000, dir_answer=b"OWNER root 755 MARKED\n")

    def h(argv, stdin, sudo):
        if argv[:2] == ["id", "-un"]:
            return RunResult(0, b"root\n", b"")
        return inner(argv, stdin, sudo)

    t, go = _stage(kit, resolved, h)
    go()
    assert any(c.kind == "put_tar" for c in t.calls)


def _is_alias_probe(argv) -> bool:
    argv = list(argv)
    if argv[:2] == ["sudo", "-n"]:
        argv = argv[2:]
    return argv[:2] == ["sh", "-c"] and "ALIAS" in argv[2]


def _alias_handler(answer: bytes, rc: int = 0):
    inner = handler_for(10_000_000)

    def h(argv, stdin, sudo):
        if _is_alias_probe(argv):
            return RunResult(rc, answer, b"")
        return inner(argv, stdin, sudo)

    return h


def test_stage_asks_the_board_about_the_state_dir_and_the_readback_base_as_root(kit, resolved):
    t, go = _stage(kit, resolved, _alias_handler(b"PLAIN\nPLAIN\n"))
    go()
    probe = next(c for c in t.calls if _is_alias_probe(c.argv))
    assert probe.sudo is True
    assert probe.argv[-2:] == [resolved.profile.state_dir, READBACK_RUN_BASE]


@pytest.mark.parametrize(
    "answer, rc",
    [(b"ALIAS\nPLAIN\n", 0), (b"PLAIN\nALIAS\n", 0), (b"PLAIN\n", 0), (b"PLAIN\nPLAIN\n", 1), (b"PLAIN\nbanana\n", 0)],
    ids=["state-dir-aliased", "readback-base-aliased", "short-answer", "probe-failed", "garbage"],
)
def test_stage_refuses_a_symlinked_state_dir_or_readback_base_before_it_copies_anything(kit, resolved, answer, rc):
    t, go = _stage(kit, resolved, _alias_handler(answer, rc))
    with pytest.raises(HostError, match="symlink"):
        go()
    assert not any(c.kind == "put_tar" for c in t.calls)
    assert not any("install" in c.argv for c in t.calls)


def test_the_alias_probe_names_a_path_behind_a_symlinked_parent_under_the_real_shell(tmp_path):
    real = tmp_path.resolve() / "real"
    real.mkdir()
    (tmp_path.resolve() / "link").symlink_to(real)
    plain, behind = str(real / "x"), str(tmp_path.resolve() / "link" / "x")
    done = subprocess.run(
        ["/bin/sh", "-c", host._ALIAS_PROBE, "sh", plain, behind], capture_output=True, text=True, check=True
    )
    assert done.stdout.split() == ["PLAIN", "ALIAS"]


def test_stage_refuses_when_the_directory_probe_itself_fails(kit, resolved):
    t, go = _stage(kit, resolved, handler_for(10_000_000, dir_answer=b"ABSENT\n", dir_rc=1))
    with pytest.raises(HostError, match="staging directory"):
        go()
    assert not any("install" in c.argv for c in t.calls)


def test_the_checksum_listing_sent_to_sha256sum_includes_the_manifest(kit, resolved):
    images, bundle_path, _ = kit
    t, go = _stage(kit, resolved, handler_for(10_000_000))
    go()
    listing = next(c.stdin_bytes for c in t.calls if c.stdin_bytes and b"profile.json" in c.stdin_bytes)
    lines = listing.decode().splitlines()
    manifest_sha = hashlib.sha256((images / "MANIFEST.hashes").read_bytes()).hexdigest()
    assert f"{manifest_sha}  MANIFEST.hashes" in lines
    assert f"{_sha(resolved.data)}  profile.json" in lines


def test_stage_writes_the_marker_restore_needs_and_lists_it_in_the_checksums(kit, resolved):
    """Restore removes a staging directory only when stage left this file in it (5.43)."""
    t, go = _stage(kit, resolved, handler_for(10_000_000))
    go()
    tar = next(c for c in t.calls if c.kind == "put_tar")
    assert STAGING_MARKER in tar.files and tar.modes[STAGING_MARKER] == 0o644
    data = tar.files[STAGING_MARKER]
    listing = next(c.stdin_bytes for c in t.calls if c.stdin_bytes and b"profile.json" in c.stdin_bytes)
    assert f"{_sha(data)}  {STAGING_MARKER}" in listing.decode().splitlines()


def test_the_stage_dry_run_names_the_marker_too(kit, resolved, capsys):
    images, bundle_path, _ = kit
    host.stage(None, resolved.profile, resolved, images, bundle_path, dry_run=True)
    assert STAGING_MARKER in capsys.readouterr().out


def test_the_stage_zip_check_runs_privileged_like_the_runner(kit, resolved):
    t, go = _stage(kit, resolved, handler_for(10_000_000))
    go()
    zcheck = next(c for c in t.calls if c.kind == "run" and any("zipfile" in a for a in c.argv))
    assert zcheck.sudo is True
    assert zcheck.argv[:3] == ["sudo", "-n", "python3"]


# --- runner-only staging --------------------------------------------------


def _stage_runner_only(kit, resolved, handler):
    _images, bundle_path, _ = kit
    t = StubTransport(handler=handler)
    return t, lambda: host.stage(t, resolved.profile, resolved, None, bundle_path, dry_run=False, runner_only=True)


def test_runner_only_stage_copies_the_bundle_profile_and_marker_with_the_same_modes(kit, resolved):
    t, go = _stage_runner_only(kit, resolved, handler_for(10_000_000))
    go()
    (tar,) = [c for c in t.calls if c.kind == "put_tar"]
    bundle_name = kit[1].name
    assert sorted(tar.files) == sorted([bundle_name, "profile.json", STAGING_MARKER])
    assert tar.modes == {bundle_name: 0o755, "profile.json": 0o644, STAGING_MARKER: 0o644}


def test_runner_only_stage_verifies_the_bundle_marker_and_profile_on_the_board_but_not_the_images(kit, resolved):
    t, go = _stage_runner_only(kit, resolved, handler_for(10_000_000))
    go()
    assert not any("MANIFEST.hashes" in " ".join(c.argv) for c in t.calls if c.kind == "run")
    listing = next(c.stdin_bytes for c in t.calls if c.stdin_bytes and b"profile.json" in c.stdin_bytes)
    names = [ln.split("  ", 1)[1] for ln in listing.decode().splitlines()]
    assert sorted(names) == sorted([kit[1].name, "profile.json", STAGING_MARKER])


def test_runner_only_stage_keeps_the_directory_ownership_rules(kit, resolved):
    t, go = _stage_runner_only(kit, resolved, handler_for(10_000_000, dir_answer=b"OWNER root 755 MARKED\n"))
    with pytest.raises(HostError, match="staging directory"):
        go()
    assert not any(c.kind == "put_tar" for c in t.calls)


def test_runner_only_dry_run_is_offline_and_names_only_the_runner_files(kit, resolved, capsys):
    host.stage(None, resolved.profile, resolved, None, kit[1], dry_run=True, runner_only=True)
    out = capsys.readouterr().out
    assert kit[1].name in out and STAGING_MARKER in out and "boot.img" not in out


# --- check_staged_build: every failure branch refuses, only an exact digest proceeds ----------------

_GOOD = "ab" * 32


def _staged_build(res):
    t = StubTransport(handler=lambda argv, stdin, sudo: res)
    return host.check_staged_build(t, "/run/x/runner.pyz", _GOOD)


@pytest.mark.parametrize(
    "res, exc, text",
    [
        (RunResult(0, b"", b""), host.HostError, host.UNVERIFIED_BUILD),
        (RunResult(1, b"", b"sha256sum: /run/x/runner.pyz: No such file or directory"), host.HostError, host.UNVERIFIED_BUILD),
        (RunResult(127, b"", b"sh: sha256sum: not found"), host.HostError, host.UNVERIFIED_BUILD),
        (RunResult(0, b"sha256sum: /run/x/runner.pyz: No such file or directory\n", b""), host.HostError, host.UNVERIFIED_BUILD),
        (RunResult(0, f"\\{_GOOD}  /run/x/ru\\nner.pyz\n".encode(), b""), host.HostError, host.UNVERIFIED_BUILD),
        (RunResult(0, f"{_GOOD[:-1]}  /run/x/runner.pyz\n".encode(), b""), host.HostError, host.UNVERIFIED_BUILD),
        (RunResult(1, f"{_GOOD}  /run/x/runner.pyz\n".encode(), b""), host.HostError, host.UNVERIFIED_BUILD),
        (RunResult(0, f"{'cd' * 32}  /run/x/runner.pyz\n".encode(), b""), host.StaleBuild, host.STALE_BUILD),
        (RunResult(255, b"", b"ssh: connect failed"), host.HostUnreachable, "staged runner's hash"),
    ],
    ids=[
        "empty-output", "rc-1", "rc-127", "error-text-rc-0", "escaped-hash", "short-hash", "digest-but-rc-1",
        "different-digest", "ssh-failure",
    ],
)
def test_check_staged_build_refuses_every_branch_but_an_exact_match(res, exc, text):
    with pytest.raises(exc, match=re.escape(text)):
        _staged_build(res)


def test_check_staged_build_accepts_the_exact_digest_in_either_case():
    assert _staged_build(RunResult(0, f"{_GOOD}  /run/x/runner.pyz\n".encode(), b"")) is None
    assert _staged_build(RunResult(0, f"{_GOOD.upper()}  /run/x/runner.pyz\n".encode(), b"")) is None
