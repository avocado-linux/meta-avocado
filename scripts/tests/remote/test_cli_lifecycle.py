"""Command-line lifecycle tests (task 6.2). Stub transport only: no ssh, no network."""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile

import pytest

from avocado_flash_remote import cli, evidence, host
from avocado_flash_remote.host import RunResult, StubTransport
from avocado_flash_remote.state import HostLock

PASSWORD = "hunter2-Zq9!"
HOST = "op@board.local"
SEVEN = "stage, check, plan, write, readback, restore, status"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Board:
    """Scripted board: answers the host's calls the way the runner would."""

    def __init__(self, tmp_path, *, need_password=False, corrupt_write=False, write_phase="complete", missing=(), interp_rc=0):
        self.missing = set(missing)
        self.interp_rc = interp_rc
        self.probes = []
        self.pythons = []
        self.tmp = tmp_path / "board"
        self.tmp.mkdir()
        self.need_password = need_password
        self.corrupt_write = corrupt_write
        self.write_phase = write_phase
        self.staged = False
        self.phase = None
        self.run_id = None
        self.requests = {}
        self.runs = []  # (sub, request, detach)
        self.records = {}  # remote run dir -> tar bytes
        self.stub = StubTransport(self.handle)
        self.log = b"runner log line\n"

    # -- record sets -------------------------------------------------------
    def _records(self, name, with_write):
        d = self.tmp / name
        d.mkdir()
        rs = evidence.RecordSet(
            d, "t", "1", "p" * 64, {"boot.img": "a" * 64}, {"id": "x"}, [],
            "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
        )
        rs.add("plan.json", {"run_id": self.run_id})
        if with_write:
            rs.add("write.json", {"ok": True})
        rs.finalize("runner-complete")
        if with_write and self.corrupt_write:
            (d / "write.json").write_bytes(b'{"ok": false}\n')
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            for p in sorted(d.iterdir()):
                tf.add(str(p), arcname="./" + p.name)
        return buf.getvalue()

    # -- handler -------------------------------------------------------------
    def handle(self, argv, stdin, sudo):
        argv = list(argv)
        if argv[:3] == ["sudo", "-n", "true"] and not sudo:
            return RunResult(0 if not self.need_password else 1)
        if argv[:2] == ["sudo", "-n"]:
            argv = argv[2:]
        elif argv[:4] == ["sudo", "-S", "-p", ""]:
            argv = argv[4:]
        if argv[:2] == ["tar", "-C"] and argv[-2:] == ["-xf", "-"]:
            self.staged = True
            return RunResult(0)
        if argv[:2] == ["tar", "-C"] and "-cf" in argv:
            return RunResult(0, self.records[argv[2]])
        if argv[:2] == ["id", "-un"]:
            return RunResult(0, b"operator\n")
        if argv[0] == "sh" and argv[2:3] and argv[2].startswith("d="):
            return RunResult(0, b"Filesystem 1024-blocks Used Available Capacity Mounted on\ntmpfs 9 1 999999 1% /run\n")
        if argv[0] == "sh" and "cat >" in argv[2]:
            self.requests[argv[-1]] = json.loads(stdin)
            return RunResult(0)
        if argv[0] == "test":
            return RunResult(0 if self.staged else 1)
        if argv[0] == "tail":
            return RunResult(0, self.log)
        if len(argv) >= 3 and argv[1] == "-c":
            self.probes.append(argv)
            if self.interp_rc:
                return RunResult(self.interp_rc, b"", b"not found")
            asked = set(re.findall(r"'([A-Za-z0-9_]+)'", argv[2]))
            gone = sorted(asked & self.missing)
            return RunResult(0, (("MISSING " + " ".join(gone)) if gone else "OK 3.12.1").encode() + b"\n")
        if argv[0].endswith("python3"):
            self.pythons.append(argv[0])
            return self._runner(argv)
        return RunResult(0)

    def _runner(self, argv):
        sub = argv[2]
        req = self.requests[argv[4]]
        self.runs.append((sub, req, "--detach" in argv))
        if sub == "check":
            return RunResult(0, b"check: all passed\n")
        if sub == "plan":
            self.run_id = req["run_id"]
            self.records[req["run_dir"]] = self._records("plan", False)
            self.phase = "planned"
            return RunResult(0, b"plan: ok\n")
        if sub == "write":
            self.records[req["run_dir"]] = self._records("write", True)
            self.phase = self.write_phase
            return RunResult(0, f"detached: run={self.run_id} log=x\n".encode())
        if sub == "restore":
            return RunResult(0, b"restore: done\n")
        if sub == "status":
            if self.phase is None:
                return RunResult(0, b"status: no run recorded\n")
            return RunResult(0, f"status: {self.phase} run={self.run_id} recovery=none-recorded\n".encode())
        return RunResult(0)

    def factory(self, host_arg, ssh_opts, batch):
        self.factory_args = (host_arg, list(ssh_opts), batch)
        return self.stub

    def subs(self):
        return [r[0] for r in self.runs]


def _plain(argv):
    argv = list(argv)
    if argv[:2] == ["sudo", "-n"]:
        return argv[2:]
    if argv[:4] == ["sudo", "-S", "-p", ""]:
        return argv[4:]
    return argv


def poisoned(*a, **k):
    raise AssertionError("transport factory must not be called")


@pytest.fixture
def images(tmp_path):
    d = tmp_path / "images"
    d.mkdir()
    lines = []
    for name in ("boot.img", "esp.img", "data.img"):
        data = (name.encode() + b"-payload") * 50
        (d / name).write_bytes(data)
        lines.append(f"{_sha(data)}  {name}\n")
    (d / "MANIFEST.hashes").write_text("".join(lines))
    return d


@pytest.fixture
def board(tmp_path):
    return Board(tmp_path)


def args(images, tmp_path, sub, *extra, host_arg=HOST):
    a = [sub, "--board", "fixture-none", "--images", str(images), "--evidence-dir", str(tmp_path / "ev")]
    if host_arg is not None:
        a += ["--host", host_arg]
    return a + list(extra)


def run(argv, board=None, **kw):
    lines = []
    kw.setdefault("sleep", lambda s: None)
    kw.setdefault("transport_factory", board.factory if board else poisoned)
    kw.setdefault("confirm", lambda prompt: "/dev/loop-fixture")
    rc = cli.main(argv, out=lines.append, **kw)
    return rc, "\n".join(map(str, lines))


def plan_run_id(tmp_path):
    dirs = sorted(p.name for p in (tmp_path / "ev").iterdir() if p.is_dir())
    return dirs[0]


# --- usage ---------------------------------------------------------------


def test_help_lists_seven_subcommands_and_gates():
    rc, text = run(["--help"])
    assert rc == 0
    for name in SEVEN.split(", "):
        assert name in text
    assert "retype" in text.lower()


def test_unknown_subcommand_lists_valid_ones(capsys):
    rc, _ = run(["frobnicate"])
    assert rc == 64
    assert f"valid subcommands: {SEVEN}" in capsys.readouterr().err


def test_missing_subcommand(capsys):
    rc, _ = run([])
    assert rc == 64
    assert f"valid subcommands: {SEVEN}" in capsys.readouterr().err


def test_missing_host_exits_64_without_connecting(images, tmp_path, capsys):
    rc, _ = run(args(images, tmp_path, "check", host_arg=None))
    assert rc == 64
    assert "--host" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["-oProxyCommand=x", "a b", "h;id"])
def test_hostile_host_rejected_before_factory(images, tmp_path, bad, capsys):
    rc, _ = run(args(images, tmp_path, "check", f"--host={bad}", host_arg=None))
    assert rc == 64
    assert "invalid ssh host" in capsys.readouterr().err


def test_host_starting_with_dash_is_a_usage_error(images, tmp_path, board):
    rc, _ = run(args(images, tmp_path, "check", host_arg="-oProxyCommand=x"), board)
    assert rc == 64
    assert board.runs == []


def test_unknown_board_exit_and_listing(images, tmp_path, capsys):
    a = args(images, tmp_path, "check")
    a[a.index("fixture-none")] = "nope"
    rc, _ = run(a)
    assert rc == 64
    assert "fixture-none" in capsys.readouterr().err


# --- stage ---------------------------------------------------------------


def test_stage_dry_run_offline_needs_no_host(images, tmp_path):
    rc, text = run(args(images, tmp_path, "stage", "--dry-run", host_arg=None))
    assert rc == 0
    assert "no connection is made" in text
    assert "profile: fixture-none" in text


def test_stage_requires_host_without_dry_run(images, tmp_path, capsys):
    rc, _ = run(args(images, tmp_path, "stage", host_arg=None))
    assert rc == 64


def test_stage_copies_to_board(images, tmp_path, board):
    rc, _ = run(args(images, tmp_path, "stage"), board)
    assert rc == 0
    assert board.staged
    assert board.factory_args[0] == HOST


def test_ssh_options_pass_through(images, tmp_path, board):
    rc, _ = run(args(images, tmp_path, "stage", "--ssh-opt=-p2222", "--batch"), board)
    assert rc == 0
    assert board.factory_args == (HOST, ["-p2222"], True)


# --- gates ---------------------------------------------------------------


def test_check_before_stage_says_run_stage_first(images, tmp_path, board, capsys):
    rc, _ = run(args(images, tmp_path, "check"), board)
    assert rc == 1
    assert "run stage first" in capsys.readouterr().err
    assert board.runs == []


def test_write_without_plan_record_refuses_with_zero_board_contact(images, tmp_path, capsys):
    rc, _ = run(args(images, tmp_path, "write", "--run-id", "run-nope"))
    assert rc == 1
    assert "no plan record for run run-nope: run plan first" in capsys.readouterr().err


def _stage_and_plan(images, tmp_path, board):
    assert run(args(images, tmp_path, "stage"), board)[0] == 0
    rc, _ = run(args(images, tmp_path, "plan"), board)
    assert rc == 0
    return plan_run_id(tmp_path)


def test_wrong_retype_refuses_and_runs_no_write(images, tmp_path, board, capsys):
    rid = _stage_and_plan(images, tmp_path, board)
    rc, _ = run(args(images, tmp_path, "write", "--run-id", rid), board, confirm=lambda p: "/dev/sda")
    assert rc == 1
    assert "write" not in board.subs()
    assert "confirmation" in capsys.readouterr().err


def test_records_failing_verification_not_complete(images, tmp_path, capsys):
    board = Board(tmp_path, corrupt_write=True)
    rid = _stage_and_plan(images, tmp_path, board)
    rc, text = run(args(images, tmp_path, "write", "--run-id", rid), board)
    assert rc == 1
    assert "records not verified" in text + capsys.readouterr().err
    assert "write COMPLETE" not in text


def test_failed_phase_is_not_complete(images, tmp_path, capsys):
    board = Board(tmp_path, write_phase="failed")
    rid = _stage_and_plan(images, tmp_path, board)
    rc, text = run(args(images, tmp_path, "write", "--run-id", rid), board)
    assert rc == 1
    assert "write COMPLETE" not in text


def test_host_lock_contention_refuses(images, tmp_path, board, capsys):
    rid = _stage_and_plan(images, tmp_path, board)
    lock_path = next((tmp_path / "ev").glob(".lock-*"), None)
    with HostLock(lock_path or (tmp_path / "ev" / ".lock-op_board.local"), HOST, "other"):
        rc, _ = run(args(images, tmp_path, "write", "--run-id", rid), board)
    assert rc == 1
    assert "held by" in capsys.readouterr().err
    assert "write" not in board.subs()


# --- full lifecycle ------------------------------------------------------


def test_full_lifecycle(images, tmp_path, board):
    # offline dry run: no connection of any kind
    rc, _ = run(args(images, tmp_path, "stage", "--dry-run", host_arg=None))
    assert rc == 0
    assert run(args(images, tmp_path, "stage"), board)[0] == 0
    rc, text = run(args(images, tmp_path, "check", "--expected-boot-order", "0001"), board)
    assert rc == 0 and "check: all passed" in text
    rc, text = run(args(images, tmp_path, "plan"), board)
    assert rc == 0
    rid = plan_run_id(tmp_path)
    assert (tmp_path / "ev" / rid / "plan.json").is_file()
    assert evidence.verify_record_set(tmp_path / "ev" / rid).ok

    rc, text = run(args(images, tmp_path, "write", "--run-id", rid, "--ack-run", rid), board)
    assert rc == 0, text
    assert "write COMPLETE" in text
    sub, req, detach = [r for r in board.runs if r[0] == "write"][0]
    assert detach is True
    assert req["confirmed_device"] == "/dev/loop-fixture"
    assert req["run_id"] == rid
    assert req["ack_run_id"] == rid
    assert req["plan_path"] == req["run_dir"] + "/plan.json"
    assert req["run_dir"] == f"/var/lib/fixture-flash/{rid}/records"
    assert req["staging_dir"] == "/run/fixture-images"

    # the plan record was collected before the board saw a write call
    plain = [_plain(c.argv) for c in board.stub.calls]
    kinds = ["py:" + a[2] if a[0] == "python3" else a[0] for a in plain]
    plan_collect = next(i for i, a in enumerate(plain) if a[:2] == ["tar", "-C"] and "-cf" in a)
    assert kinds.index("py:plan") < plan_collect < kinds.index("py:write")

    rc, text = run(args(images, tmp_path, "status"), board)
    assert rc == 0 and "status: complete" in text
    rc, text = run(args(images, tmp_path, "restore", "--ack-run", rid), board)
    assert rc == 0 and "restore: done" in text
    assert board.subs() == ["check", "plan", "write", "status", "status", "restore"]
    restore_req = board.runs[-1][1]
    assert restore_req["ack_run_id"] == rid
    assert restore_req["emergency_disarm"] is False


def test_emergency_disarm_flag(images, tmp_path, board):
    _stage_and_plan(images, tmp_path, board)
    rc, _ = run(args(images, tmp_path, "restore", "--emergency-disarm"), board)
    assert rc == 0
    assert board.runs[-1][1]["emergency_disarm"] is True


def test_runner_exit_code_passes_through(images, tmp_path, board):
    orig = board.handle

    def h(argv, stdin, sudo):
        res = orig(argv, stdin, sudo)
        if "python3" in argv and "check" in argv:
            return RunResult(2, b"check: not examined\n")
        return res

    board.stub.handler = h
    assert run(args(images, tmp_path, "stage"), board)[0] == 0
    rc, _ = run(args(images, tmp_path, "check"), board)
    assert rc == 2


# --- hygiene -------------------------------------------------------------


def test_password_never_printed(images, tmp_path, capsys):
    board = Board(tmp_path, need_password=True)
    assert run(args(images, tmp_path, "stage"), board, ask_password=lambda: PASSWORD)[0] == 0
    rc, text = run(args(images, tmp_path, "status"), board, ask_password=lambda: PASSWORD)
    captured = capsys.readouterr()
    assert PASSWORD not in text + captured.out + captured.err


def test_unexpected_error_is_one_line_not_traceback(images, tmp_path, capsys):
    def boom(*a, **k):
        raise RuntimeError("kaput")

    rc, _ = run(args(images, tmp_path, "status"), transport_factory=boom)
    err = capsys.readouterr().err
    assert rc == 70
    assert "avocado-flash ssh-emmc: error: RuntimeError: kaput" in err
    assert "Traceback" not in err


def test_interrupt_exits_130(images, tmp_path, capsys):
    def boom(*a, **k):
        raise KeyboardInterrupt

    rc, _ = run(args(images, tmp_path, "status"), transport_factory=boom)
    assert rc == 130


# --- remote interpreter (task 6.4) -----------------------------------------

TARGET_MISSING = "hashlib _hashlib _sha2 json tempfile datetime socket getpass base64 random uuid secrets".split()
BOARD_SUBS = ["check", "plan", "write", "readback", "restore", "status"]


def _sub_args(images, tmp_path, sub, rid="run-x"):
    extra = {
        "write": ["--run-id", rid],
        "readback": ["--reference-boot-order", "0001"],
        "restore": ["--ack-run", rid],
    }.get(sub, [])
    return args(images, tmp_path, sub, *extra)


def _prepared(images, tmp_path):
    """Stage and plan on a full interpreter; returns (board, run id)."""
    board = Board(tmp_path)
    rid = _stage_and_plan(images, tmp_path, board)
    return board, rid


@pytest.mark.parametrize("sub", BOARD_SUBS)
def test_missing_stdlib_refuses_before_any_runner_call(images, tmp_path, sub, capsys):
    board, rid = _prepared(images, tmp_path)
    before = len(board.stub.calls)
    board.missing = set(TARGET_MISSING)
    board.requests.clear()
    board.runs.clear()
    rc, _ = run(_sub_args(images, tmp_path, sub, rid), board)
    err = capsys.readouterr().err
    assert rc == 1
    assert board.runs == [] and board.requests == {}
    for name in ("hashlib", "json", "datetime"):
        assert name in err
    assert "python3" in err and "--remote-python" in err
    assert not [c for c in board.stub.calls[before:] if c.stdin_len and b"staging_dir" in (c.stdin_bytes or b"")]


def test_missing_stdlib_refuses_stage_too(images, tmp_path, capsys):
    board = Board(tmp_path, missing=TARGET_MISSING)
    rc, _ = run(args(images, tmp_path, "stage"), board)
    assert rc == 1
    assert not board.staged
    assert "--remote-python" in capsys.readouterr().err


@pytest.mark.parametrize("sub", BOARD_SUBS)
def test_full_interpreter_proceeds_and_prints_line_once(images, tmp_path, sub):
    if sub == "plan":  # a second plan in the same second would reuse the run id
        board, rid = Board(tmp_path), "run-x"
        assert run(args(images, tmp_path, "stage"), board)[0] == 0
    else:
        board, rid = _prepared(images, tmp_path)
    rc, text = run(_sub_args(images, tmp_path, sub, rid), board)
    assert rc == 0, text
    assert text.count("remote python: python3 3.12.1") == 1
    assert sub in board.subs()


def test_probe_runs_after_privilege_and_before_runner(images, tmp_path):
    board, rid = _prepared(images, tmp_path)
    board.stub.calls.clear()
    run(_sub_args(images, tmp_path, "status"), board)
    plain = [_plain(c.argv) for c in board.stub.calls]
    idx = lambda pred: next(i for i, a in enumerate(plain) if pred(a))  # noqa: E731
    uid = idx(lambda a: a[:2] == ["id", "-u"])
    probe = idx(lambda a: a[:2] == ["python3", "-c"])
    req = idx(lambda a: a[0] == "sh" and "cat >" in a[2])
    assert uid < probe < req


def test_interpreter_not_found_message(images, tmp_path, capsys):
    board = Board(tmp_path, interp_rc=127)
    rc, _ = run(args(images, tmp_path, "stage"), board)
    err = capsys.readouterr().err
    assert rc == 1 and "not found" in err and "--remote-python" in err


def test_remote_python_option_reaches_probe_and_runner(images, tmp_path):
    board = Board(tmp_path)
    assert run(args(images, tmp_path, "stage", "--remote-python", "/opt/py/bin/python3"), board)[0] == 0
    rc, text = run(args(images, tmp_path, "check", "--remote-python", "/opt/py/bin/python3"), board)
    assert rc == 0
    assert "remote python: /opt/py/bin/python3 3.12.1" in text
    assert board.probes[-1][0] == "/opt/py/bin/python3"
    assert board.pythons[-1] == "/opt/py/bin/python3"
    assert "python3" not in [p for p in board.pythons if p != "/opt/py/bin/python3"]


@pytest.mark.parametrize("bad", ["-oFoo", "a b", "../x", "$(x)", "", "x/../y", "a;b"])
@pytest.mark.parametrize("sub", ["check", "stage"])
def test_hostile_remote_python_rejected_before_factory(images, tmp_path, bad, sub, capsys):
    rc, _ = run(args(images, tmp_path, sub, f"--remote-python={bad}"))
    assert rc == 64
    assert "--remote-python" in capsys.readouterr().err
