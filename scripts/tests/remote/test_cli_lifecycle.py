"""Command-line lifecycle tests (task 6.2). Stub transport only: no ssh, no network."""

from __future__ import annotations

import hashlib
import io
import json
import re
import pathlib
import tarfile

import pytest

from avocado_flash_remote import cli, evidence, host
from avocado_flash_remote.host import RunResult, StubTransport
from avocado_flash_remote.profile import READBACK_RUN_BASE
from avocado_flash_remote.state import HostLock

PASSWORD = "hunter2-Zq9!"
HOST = "op@board.local"
PROFILES = pathlib.Path(host.__file__).resolve().parent / "profiles"
SEVEN = "stage, check, plan, write, readback, restore, status"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def expected_bundle_sha() -> str:
    """The sha256 of the bundle this tool builds for the fixture profile (the build is deterministic)."""
    import tempfile

    from avocado_flash_remote.bundle import build_bundle
    from avocado_flash_remote.profile_resolve import resolve_profile

    with tempfile.TemporaryDirectory() as tmp:
        data = resolve_profile("fixture-none", None).data
        return build_bundle(data, pathlib.Path(tmp) / "runner.pyz", cli.TOOL_VERSION).sha256


class Board:
    """Scripted board: answers the host's calls the way the runner would."""

    def __init__(self, tmp_path, *, need_password=False, corrupt_write=False, write_phase="complete", missing=(), interp_rc=0):
        self.bundle_sha = None  # what sha256sum says about the staged bundle; None means the tool's own build
        self.bundle_hash_rc = 0  # a failing sha256sum of the staged bundle
        self.unreachable_at = None  # 'test', 'id' or 'sudo': that connect probe answers ssh's 255
        self.omit_write_json = False  # the write record set lacks write.json (still a verifying set)
        self.write_run_status = "runner-complete"  # run_status of the write record set's manifest
        self.timeout_sub = None  # the runner call that times out on the host side (ssh wait expired)
        self.accepted = True  # the runner's `accepted` marker exists once write is detached
        self.runner_alive = False
        self.outcome = None  # the runner's `outcome` marker body (bytes) once it has ended
        self.probe_fail = None  # a RunResult every presence probe (markers, /proc) answers with
        self.accepted_fail_times = 0  # the first N reads of the accepted marker fail (an ssh blip), then it is readable
        self.accepted_nonce = None  # override the nonce the accepted marker carries (another invocation's)
        self.write_err = b""
        self.complete_on_proc_probe = False  # the write finishes between the poll and the probe
        self.hidden_polls = 0  # status answers "no run recorded" this many times after write
        self.write_rc = 0
        self.recovery = "none-recorded"
        self.advance_after = None  # status answers write_phase, then 'complete' after this many polls
        self.status_calls = 0
        self.status_unreadable = False  # after write, status reports the per-run record as unreadable (rc 1)
        self.cat_calls = []
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
        self.wrote = False
        self.phase = None
        self.run_id = None
        self.requests = {}
        self.runs = []  # (sub, request, detach)
        self.records = {}  # remote run dir -> tar bytes
        self.stub = StubTransport(self.handle)
        self.staged_sha = None  # the sha256 of the bundle the host last copied here, as sha256sum would say
        real_put_tar = self.stub.put_tar

        def put_tar(files, dest_dir, modes=None, **kw):
            self.staged_sha = _sha(pathlib.Path(files[cli.BUNDLE_NAME]).read_bytes())
            return real_put_tar(files, dest_dir, modes, **kw)

        self.stub.put_tar = put_tar
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
        if with_write and not self.omit_write_json:
            rs.add("write.json", {"ok": True})
        rs.finalize(self.write_run_status if with_write else "runner-complete")
        if with_write and self.corrupt_write:
            (d / "write.json").write_bytes(b'{"ok": false}\n')
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            for p in sorted(d.iterdir()):
                tf.add(str(p), arcname="./" + p.name)
        return buf.getvalue()

    def _nonce(self):
        """The nonce of the write request this board last received."""
        for sub, req, _detach in reversed(self.runs):
            if sub == "write":
                return req["invocation_nonce"]
        return "0" * 16

    # -- handler -------------------------------------------------------------
    def handle(self, argv, stdin, sudo):
        argv = list(argv)
        if argv[:3] == ["sudo", "-n", "true"] and not sudo:
            if self.unreachable_at == "sudo":
                return SSH_DROP
            return RunResult(0 if not self.need_password else 1)
        if argv[:2] == ["id", "-u"] and self.unreachable_at == "id":
            return SSH_DROP
        if argv[:2] == ["sudo", "-n"]:
            argv = argv[2:]
        elif argv[:4] == ["sudo", "-S", "-p", ""]:
            argv = argv[4:]
        if argv[:2] == ["tar", "-C"] and argv[-2:] == ["-xf", "-"]:
            self.staged = True
            return RunResult(0)
        if argv[:2] == ["tar", "-C"] and "-cf" in argv:
            return RunResult(0, self.records[argv[2]])
        if argv[:2] == ["sh", "-c"] and "--version" in argv[2] and "sha256sum" in argv[2]:
            return RunResult(0, b"OK\n")
        if argv[:2] == ["id", "-un"]:
            return RunResult(0, b"operator\n")
        if argv[0] == "sh" and "stat -c" in argv[2]:
            return RunResult(0, b"ABSENT\n")  # the staging directory does not exist yet
        if argv[0] == "sh" and argv[2:3] and argv[2].startswith("d="):
            return RunResult(0, b"Filesystem 1024-blocks Used Available Capacity Mounted on\ntmpfs 9 1 999999 1% /run\n")
        if argv[0] == "sh" and "cat >" in argv[2]:
            self.requests[argv[-1]] = json.loads(stdin)
            return RunResult(0)
        if argv[0] == "sh" and "command -v" in argv[2]:  # the interpreter lookup, answering its own exit code
            return RunResult(127 if self.interp_rc else 0)
        if argv[0] == "sh" and "/proc/" in argv[2]:
            if self.probe_fail is not None:
                return self.probe_fail
            if self.complete_on_proc_probe:
                self.phase = "complete"
            return RunResult(0, b"alive\n" if self.runner_alive else b"gone\n")
        if argv[0] == "sh" and "exit 3" in argv[2] and argv[-1].endswith("/outcome"):
            if self.probe_fail is not None:
                return self.probe_fail
            if self.outcome is not None:
                return RunResult(0, self.outcome.replace(b"@NONCE@", self._nonce().encode()))
            return RunResult(3)
        if argv[0] == "sh" and "exit 3" in argv[2] and argv[-1].endswith("/accepted"):
            self.cat_calls.append(argv[-1])
            if self.accepted_fail_times > 0:
                self.accepted_fail_times -= 1
                return SSH_DROP
            if self.probe_fail is not None:
                return self.probe_fail
            if self.accepted and self.wrote:
                return RunResult(0, f"4242\nnonce={self.accepted_nonce or self._nonce()}\n".encode())
            return RunResult(3)
        if argv[0] == "test":
            if self.unreachable_at == "test":
                return SSH_DROP
            return RunResult(0 if self.staged else 1)
        if argv[0] == "sha256sum":
            if self.bundle_hash_rc:
                return RunResult(self.bundle_hash_rc, b"", b"sha256sum: no such file")
            digest = self.bundle_sha or self.staged_sha or expected_bundle_sha()
            return RunResult(0, f"{digest}  {argv[-1]}\n".encode())
        if argv[0] == "tail":
            return RunResult(0, self.log)
        if len(argv) >= 3 and argv[1] == "-c":
            self.probes.append(argv)
            if self.interp_rc:
                # What sudo returns for a missing command: exit 1 and its own words, never 127.
                return RunResult(self.interp_rc, b"", f"sudo: {argv[0]}: command not found".encode())
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
        if sub == self.timeout_sub:
            raise host.HostTimeout("ssh to the board timed out after 1s")
        if sub == "check":
            return RunResult(0, b"check: all passed\n")
        if sub == "plan":
            self.run_id = req["run_id"]
            self.records[req["run_dir"]] = self._records("plan", False)
            self.phase = "planned"
            return RunResult(0, b"plan: ok\n")
        if sub == "write":
            self.records[req["run_dir"]] = self._records("write", True)
            self.wrote = True
            self.phase = self.write_phase
            if self.write_rc:
                return RunResult(self.write_rc, b"", self.write_err or b"ssh: connection reset")
            return RunResult(0, f"detached: run={self.run_id} log=x\n".encode())
        if sub == "restore":
            return RunResult(0, b"restore: done\n")
        if sub == "status":
            if self.wrote and self.status_unreadable:
                return RunResult(1, f"status: state unreadable run={req.get('run_id')}: state.json: Expecting value\n".encode())
            if self.wrote and self.hidden_polls > 0:
                self.hidden_polls -= 1
                return RunResult(0, b"status: no run recorded\n")
            if self.phase is None:
                return RunResult(0, b"status: no run recorded\n")
            self.status_calls += 1
            if self.advance_after is not None and self.status_calls > self.advance_after:
                self.phase = "complete"
            return RunResult(0, f"status: {self.phase} run={self.run_id} recovery={self.recovery}\n".encode())
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


# --- 5.14: a slow or dropped runner is never reported as not started -----


def _write(images, tmp_path, board, *extra):
    rid = _stage_and_plan(images, tmp_path, board)
    return run(args(images, tmp_path, "write", "--run-id", rid, *extra), board)


def test_slow_runner_that_has_accepted_is_not_reported_as_not_started(images, tmp_path, capsys):
    board = Board(tmp_path)
    board.hidden_polls = 10  # still hashing: no state for far longer than three polls
    board.runner_alive = True
    rc, text = _write(images, tmp_path, board)
    assert rc == 0, text
    assert "did not start" not in text + capsys.readouterr().err
    assert "write COMPLETE" in text


def test_accepted_marker_alone_keeps_the_host_waiting(images, tmp_path, capsys):
    board = Board(tmp_path)
    board.hidden_polls = 10
    board.runner_alive = False  # marker present, process not visible: still not "never started"
    rc, text = _write(images, tmp_path, board)
    assert "the write did not start" not in text + capsys.readouterr().err


def test_never_started_run_is_reported_and_points_at_status(images, tmp_path, capsys):
    board = Board(tmp_path)
    board.accepted = False
    board.hidden_polls = 10**6
    board.runner_alive = False
    rc, text = _write(images, tmp_path, board)
    assert rc == 1
    assert "did not start" in text
    assert "status" in text
    assert "before assuming nothing happened" in text


ARMING_RECOVERY = (
    "restore-unknown-arm: the arm step started: a boot entry may already exist. DO NOT REBOOT. "
    "Run restore with --ack-run RUN_ID"
)


def test_runner_exited_in_arming_stops_the_host_follow_loop(images, tmp_path, capsys):
    board = Board(tmp_path, write_phase="arming")
    board.recovery = ARMING_RECOVERY
    board.runner_alive = False  # accepted marker names a pid that is gone
    rc, text = _write(images, tmp_path, board, "--wait-seconds", "100000")
    assert rc == 1
    assert "still in progress" not in text
    assert "arming" in text
    assert "DO NOT REBOOT" in text
    assert "write COMPLETE" not in text
    assert board.status_calls <= 5  # stopped within the poll window, not after 100000 s of polls


def test_live_runner_in_non_terminal_phase_keeps_being_followed(images, tmp_path, capsys):
    board = Board(tmp_path, write_phase="image-writing")
    board.runner_alive = True
    board.advance_after = 8  # same phase for eight polls, then the run completes
    rc, text = _write(images, tmp_path, board)
    assert rc == 0, text
    assert "write COMPLETE" in text
    assert board.status_calls > 8


def test_live_runner_that_never_finishes_ends_at_wait_seconds_not_as_exited(images, tmp_path):
    board = Board(tmp_path, write_phase="arming")
    board.runner_alive = True
    rc, text = _write(images, tmp_path, board, "--wait-seconds", "50")
    assert rc == 1
    assert "still in progress" in text
    assert "exited" not in text


def test_dropped_connection_after_detach_reconciles_and_reports_true_phase(images, tmp_path, capsys):
    board = Board(tmp_path)
    board.write_rc = 255
    rc, text = _write(images, tmp_path, board)
    assert rc == 0, text
    assert "write COMPLETE" in text
    assert "connection" in (text + capsys.readouterr().err).lower()


def test_dropped_connection_after_detach_with_failed_phase_is_not_255(images, tmp_path):
    board = Board(tmp_path, write_phase="failed")
    board.write_rc = 255
    rc, text = _write(images, tmp_path, board)
    assert rc == 1
    assert "write COMPLETE" not in text


@pytest.mark.parametrize("sub", ["check", "status", "restore", "plan", "readback"])
def test_exit_255_is_never_returned(images, tmp_path, sub, capsys):
    board = Board(tmp_path)
    assert run(args(images, tmp_path, "stage"), board)[0] == 0
    orig = board._runner

    def dropped(argv):
        if argv[2] == sub:
            return RunResult(255, b"", b"ssh: connection reset")
        return orig(argv)

    board._runner = dropped
    extra = ["--emergency-disarm"] if sub == "restore" else []
    rc, _ = run(args(images, tmp_path, sub, *extra), board)
    assert rc == 2
    assert "status" in capsys.readouterr().err


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
    board = Board(tmp_path, interp_rc=1)
    rc, _ = run(args(images, tmp_path, "stage"), board)
    err = capsys.readouterr().err
    assert rc == 1 and "interpreter not found" in err and "--remote-python" in err


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


# --- 5.19: unknown stays unknown, a refusal is a refusal --------------------

SSH_DROP = RunResult(255, b"", b"ssh: connection reset")
SUDO_FAIL = RunResult(1, b"", b"sudo: a password is required")
REFUSAL = (
    "write refused: run r1 already has a state record under /var/lib/x; it is never "
    "overwritten: run plan again for a new run id\nnothing was written to the board"
)


@pytest.mark.parametrize("fail", [SSH_DROP, SUDO_FAIL], ids=["ssh-drop", "sudo-failure"])
def test_unreadable_markers_never_produce_a_not_started_or_exited_verdict(images, tmp_path, capsys, fail):
    board = Board(tmp_path)
    board.hidden_polls = 10**6  # no state is ever visible
    board.probe_fail = fail
    rc, text = _write(images, tmp_path, board, "--wait-seconds", "50")
    all_text = text + capsys.readouterr().err
    assert rc == 1
    assert "did not start" not in all_text
    assert "may have been changed" not in all_text
    assert "exited" not in all_text
    assert "still in progress" in all_text


@pytest.mark.parametrize("fail", [SSH_DROP, SUDO_FAIL], ids=["ssh-drop", "sudo-failure"])
def test_failed_proc_probe_does_not_end_the_follow_but_withholds_complete(images, tmp_path, fail):
    board = Board(tmp_path, write_phase="image-writing")
    board.runner_alive = True  # it is alive, but the probe cannot say so
    board.probe_fail = fail
    board.advance_after = 8
    rc, text = _write(images, tmp_path, board)
    assert "exited" not in text  # the follow went on to the board's terminal phase
    assert board.status_calls > 8
    # Whose runner finished the run cannot be read either, so COMPLETE is withheld rather than guessed.
    assert rc == 1
    assert "write COMPLETE" not in text
    # Reworded: "did not write it" is only for another invocation's run or none at all, never for an
    # unreadable marker, so the unknown now says it could not confirm and points at status.
    assert "could not confirm which invocation wrote it" in text and "status subcommand" in text
    assert "did not write it" not in text


def test_proc_probe_and_marker_read_run_with_the_same_privilege(images, tmp_path):
    board = Board(tmp_path, write_phase="arming")
    board.runner_alive = False
    _write(images, tmp_path, board, "--wait-seconds", "100000")
    probes = [c for c in board.stub.calls if c.argv and ("/proc/" in " ".join(map(str, c.argv)) or "accepted" in " ".join(map(str, c.argv)))]
    assert probes
    assert all(c.argv[:2] in (["sudo", "-n"],) for c in probes), [c.argv for c in probes]


def test_pre_lock_refusal_is_printed_verbatim_and_not_called_a_possible_change(images, tmp_path, capsys):
    board = Board(tmp_path)
    board.hidden_polls = 10**6
    board.runner_alive = False  # the marker names a pid that is gone
    board.outcome = ("refused\nrun=%s\nnonce=@NONCE@\n%s\n" % ("RID", REFUSAL)).encode()
    rid = _stage_and_plan(images, tmp_path, board)
    board.outcome = board.outcome.replace(b"RID", rid.encode())
    rc, text = run(args(images, tmp_path, "write", "--run-id", rid), board)
    all_text = text + capsys.readouterr().err
    assert rc == 1
    assert REFUSAL in all_text
    assert "may have been changed" not in all_text
    assert "did not start" not in all_text
    assert "write COMPLETE" not in all_text


def test_refusal_from_another_run_is_not_trusted(images, tmp_path, capsys):
    board = Board(tmp_path)
    board.hidden_polls = 10**6
    board.runner_alive = True  # a recycled pid would read as alive
    board.outcome = ("refused\nrun=SOMEONE-ELSE\nnonce=@NONCE@\n%s\n" % REFUSAL).encode()
    rc, text = _write(images, tmp_path, board, "--wait-seconds", "50")
    all_text = text + capsys.readouterr().err
    assert rc == 1
    assert REFUSAL not in all_text
    assert "still in progress" in all_text


def test_refused_replay_exits_nonzero_with_the_refusal_and_never_prints_complete(images, tmp_path, capsys):
    board = Board(tmp_path)
    board.write_rc = 1
    board.write_err = REFUSAL.encode()
    rc, text = _write(images, tmp_path, board)
    all_text = text + capsys.readouterr().err
    assert rc == 1
    assert REFUSAL in all_text
    assert "COMPLETE" not in all_text
    assert board.status_calls == 0  # the host never followed a run that was never started


def _write_nonces(board):
    return [req["invocation_nonce"] for sub, req, _d in board.runs if sub == "write"]


def test_every_write_invocation_sends_a_fresh_nonce(images, tmp_path):
    seen = []
    for n in range(2):
        (tmp_path / f"b{n}").mkdir()
        board = Board(tmp_path / f"b{n}")
        rc, _ = _write(images, tmp_path / f"b{n}", board)
        assert rc == 0
        seen += _write_nonces(board)
    assert len(seen) == 2 and seen[0] != seen[1]
    assert all(re.fullmatch(r"[0-9a-f]{16,64}", n) for n in seen)


def test_complete_phase_of_another_invocations_run_is_not_this_invocations_complete(images, tmp_path, capsys):
    # The refused replay's connection dropped: the follow sees the earlier run's complete phase.
    board = Board(tmp_path)
    board.write_rc = 255
    board.accepted_nonce = "e5" * 8
    rc, text = _write(images, tmp_path, board)
    all_text = text + capsys.readouterr().err
    assert rc == 1
    assert "write COMPLETE" not in all_text
    assert "this invocation did not write" in all_text
    assert "complete" in all_text  # the run's own phase is still reported


def test_complete_phase_with_no_accepted_marker_is_not_this_invocations_complete(images, tmp_path, capsys):
    board = Board(tmp_path)
    board.write_rc = 255
    board.accepted = False
    rc, text = _write(images, tmp_path, board)
    all_text = text + capsys.readouterr().err
    assert rc == 1
    assert "write COMPLETE" not in all_text
    assert "this invocation did not write" in all_text


def test_complete_phase_with_an_unreadable_accepted_marker_is_not_reported_as_complete(images, tmp_path, capsys):
    board = Board(tmp_path)
    board.probe_fail = SUDO_FAIL
    rc, text = _write(images, tmp_path, board)
    all_text = text + capsys.readouterr().err
    assert rc == 1
    assert "write COMPLETE" not in all_text


def test_one_ssh_blip_on_the_owner_probe_does_not_withhold_our_own_complete(images, tmp_path):
    board = Board(tmp_path)
    board.accepted_fail_times = 1
    rc, text = _write(images, tmp_path, board)
    assert rc == 0 and "write COMPLETE" in text
    assert "did not write it" not in text
    assert len([c for c in board.cat_calls if c.endswith("/accepted")]) == 2


def test_an_owner_probe_that_stays_unreadable_is_unknown_never_did_not_write_it(images, tmp_path, capsys):
    board = Board(tmp_path)
    board.accepted_fail_times = 10**6
    rc, text = _write(images, tmp_path, board)
    all_text = text + capsys.readouterr().err
    assert rc == 1 and "write COMPLETE" not in all_text
    assert "could not confirm which invocation wrote it" in all_text
    assert "did not write it" not in all_text
    # bounded: within --wait-seconds, not forever
    assert len([c for c in board.cat_calls if c.endswith("/accepted")]) <= 10


def test_a_marker_that_is_another_invocations_still_says_it_did_not_write_it(images, tmp_path):
    board = Board(tmp_path)
    board.accepted_nonce = "e5" * 8
    rc, text = _write(images, tmp_path, board)
    assert rc == 1 and "did not write it" in text


def test_complete_phase_with_our_refusal_recorded_is_not_complete(images, tmp_path, capsys):
    board = Board(tmp_path)
    rid = _stage_and_plan(images, tmp_path, board)
    board.outcome = f"refused\nrun={rid}\nnonce=@NONCE@\nwhy\n".encode()
    rc, text = run(args(images, tmp_path, "write", "--run-id", rid), board)
    assert rc == 1
    assert "write COMPLETE" not in text + capsys.readouterr().err


def test_second_host_refused_by_a_running_write_never_says_nothing_changed(images, tmp_path, capsys):
    board = Board(tmp_path)
    board.write_rc = 1
    board.write_err = (
        "write refused: run RID is already in progress under another invocation; this invocation did not "
        "start and left the running one as it was. The board may be changing: follow the running write "
        "with the status subcommand and do not start another"
    ).encode()
    rc, text = _write(images, tmp_path, board)
    all_text = (text + capsys.readouterr().err).lower()
    assert rc == 1
    assert "already in progress" in all_text
    assert "nothing" not in all_text and "unchanged" not in all_text
    assert "write complete" not in all_text
    assert board.status_calls == 0


def test_completion_between_the_poll_and_the_presence_probe_is_reported_as_complete(images, tmp_path, capsys):
    board = Board(tmp_path, write_phase="image-writing")
    board.runner_alive = False
    board.complete_on_proc_probe = True  # the runner ends normally just before the probe answers
    rc, text = _write(images, tmp_path, board)
    assert rc == 0, text + capsys.readouterr().err
    assert "write COMPLETE" in text
    assert "exited" not in text


# ---- 5.25: status honours --run-id; an unreadable record is never "still in progress"


def test_the_status_subcommand_forwards_run_id_to_the_runner(images, tmp_path):
    board = Board(tmp_path)
    rid = _stage_and_plan(images, tmp_path, board)
    board.runs.clear()
    rc, _text = run(args(images, tmp_path, "status", "--run-id", rid), board)
    assert rc == 0
    assert [req.get("run_id") for sub, req, _d in board.runs if sub == "status"] == [rid]


def test_the_status_subcommand_without_run_id_asks_for_the_current_run(images, tmp_path):
    board = Board(tmp_path)
    _stage_and_plan(images, tmp_path, board)
    board.runs.clear()
    rc, _text = run(args(images, tmp_path, "status"), board)
    assert rc == 0
    assert "run_id" not in [req for sub, req, _d in board.runs if sub == "status"][0]


def test_a_hostile_run_id_on_status_is_refused_before_the_board_is_contacted(images, tmp_path):
    board = Board(tmp_path)
    _stage_and_plan(images, tmp_path, board)
    board.runs.clear()
    rc, _text = run(args(images, tmp_path, "status", "--run-id", "../x"), board)
    assert rc != 0 and board.runs == []


def test_host_messages_that_point_at_status_name_the_run_id(images, tmp_path):
    board = Board(tmp_path)
    board.accepted = False
    board.hidden_polls = 10**6
    board.runner_alive = False
    rid = _stage_and_plan(images, tmp_path, board)
    rc, text = run(args(images, tmp_path, "write", "--run-id", rid), board)
    assert rc == 1 and f"--run-id {rid}" in text


def test_a_dead_runner_with_an_unreadable_record_is_reported_unreadable_not_in_progress(images, tmp_path):
    board = Board(tmp_path)
    board.status_unreadable = True
    board.runner_alive = False
    rid = _stage_and_plan(images, tmp_path, board)
    rc, text = run(args(images, tmp_path, "write", "--run-id", rid, "--wait-seconds", "100000"), board)
    assert rc == 1
    assert "still in progress" not in text
    assert f"record for run {rid} is unreadable" in text
    assert f"--run-id {rid}" in text
    assert "write COMPLETE" not in text


def test_an_unreadable_record_with_a_live_runner_still_never_reads_as_in_progress_at_the_end(images, tmp_path):
    board = Board(tmp_path)
    board.status_unreadable = True
    board.runner_alive = True
    rid = _stage_and_plan(images, tmp_path, board)
    rc, text = run(args(images, tmp_path, "write", "--run-id", rid, "--wait-seconds", "30"), board)
    assert rc == 1
    assert "still in progress" not in text
    assert f"record for run {rid} is unreadable" in text


def test_restore_names_the_run_it_was_asked_for(images, tmp_path, board):
    _stage_and_plan(images, tmp_path, board)
    rid = plan_run_id(tmp_path)
    rc, _ = run(args(images, tmp_path, "restore", "--run-id", rid, "--ack-run", rid), board)
    assert rc == 0
    assert board.runs[-1][1]["run_id"] == rid


def test_restore_without_run_id_sends_none(images, tmp_path, board):
    _stage_and_plan(images, tmp_path, board)
    rc, _ = run(args(images, tmp_path, "restore", "--emergency-disarm"), board)
    assert rc == 0
    assert "run_id" not in board.runs[-1][1]


def test_collect_in_the_marker_window_is_retried_until_the_records_verify(images, tmp_path, board, monkeypatch):
    """The board's phase turns complete a moment before the manifest and outcome marker land."""
    _stage_and_plan(images, tmp_path, board)
    good = {}
    real_handle = board.handle
    state = {"collects": 0}

    def handle(argv, stdin, sudo):
        plain = _plain(argv)
        if plain[:2] == ["tar", "-C"] and "-cf" in plain and board.wrote:
            state["collects"] += 1
            good.setdefault("raw", board.records[plain[2]])
            if state["collects"] == 1:
                board._records("window", True)
                return RunResult(0, _tar_of(board.tmp / "window", drop="MANIFEST.json"))
        return real_handle(argv, stdin, sudo)

    board.stub.handler = handle
    rid = plan_run_id(tmp_path)
    rc, text = run(args(images, tmp_path, "write", "--run-id", rid, "--ack-run", rid), board)
    assert state["collects"] >= 2
    assert rc == 0 and "write COMPLETE" in text


def test_collect_is_not_retried_once_the_runner_outcome_is_final(images, tmp_path, board):
    board.corrupt_write = True
    _stage_and_plan(images, tmp_path, board)
    rid = plan_run_id(tmp_path)
    board.outcome = f"finished\nrun={rid}\nnonce=@NONCE@\n".encode()
    collects = []
    real_handle = board.handle

    def handle(argv, stdin, sudo):
        plain = _plain(argv)
        if plain[:2] == ["tar", "-C"] and "-cf" in plain and board.wrote:
            collects.append(1)
        return real_handle(argv, stdin, sudo)

    board.stub.handler = handle
    rc, _ = run(args(images, tmp_path, "write", "--run-id", rid, "--ack-run", rid), board)
    assert rc == 1
    assert len(collects) == 1


def _tar_of(directory, drop=None):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for p in sorted(directory.iterdir()):
            if p.name != drop:
                tf.add(str(p), arcname="./" + p.name)
    return buf.getvalue()


def test_record_producing_requests_carry_the_tool_version_and_a_host_clock(images, tmp_path, board):
    _stage_and_plan(images, tmp_path, board)
    rid = plan_run_id(tmp_path)
    rc, _ = run(args(images, tmp_path, "write", "--run-id", rid, "--ack-run", rid), board)
    assert rc == 0
    for sub in ("plan", "write"):
        req = [r for r in board.runs if r[0] == sub][0][1]
        assert req["tool_version"] == cli.TOOL_VERSION
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", req["host_utc"])


def test_collect_is_retried_when_the_outcome_is_published_before_the_manifest_lists_it(images, tmp_path, board):
    """The runner writes the outcome marker, then the manifest that lists it; a collect between the two
    sees the marker unlisted. The marker is final, so only the verification problem says to look again."""
    _stage_and_plan(images, tmp_path, board)
    rid = plan_run_id(tmp_path)
    board.outcome = f"finished\nrun={rid}\nnonce=@NONCE@\n".encode()
    real_handle = board.handle
    state = {"collects": 0}

    def handle(argv, stdin, sudo):
        plain = _plain(argv)
        if plain[:2] == ["tar", "-C"] and "-cf" in plain and board.wrote:
            state["collects"] += 1
            if state["collects"] == 1:
                board._records("early", True)
                (board.tmp / "early" / "outcome").write_bytes(b"finished\n")
                return RunResult(0, _tar_of(board.tmp / "early"))
        return real_handle(argv, stdin, sudo)

    board.stub.handler = handle
    rc, text = run(args(images, tmp_path, "write", "--run-id", rid, "--ack-run", rid), board)
    assert state["collects"] >= 2
    assert rc == 0 and "write COMPLETE" in text


# --- final ds-verify fixes (task 5.34) -----------------------------------------


def test_readback_refuses_a_run_id_with_a_slash_before_any_connection(images, tmp_path, capsys):
    rc, _ = run(args(images, tmp_path, "readback", "--run-id", "../../etc"), None)
    assert rc == 64
    assert "invalid run id" in capsys.readouterr().err


def test_readback_still_accepts_a_plain_run_id(images, tmp_path):
    board, _rid = _prepared(images, tmp_path)
    rc, _ = run(args(images, tmp_path, "readback", "--run-id", "rb-1"), board)
    assert rc == 0
    req = [r for sub, r, _d in board.runs if sub == "readback"][0]
    assert req["run_id"] == "rb-1"


# --- task 5.38: readback output and mount point live on tmpfs under /run -------
# (5.43: the runner derives both from the run id; the request names neither)


def _readback_request(images, tmp_path, *extra):
    board, _rid = _prepared(images, tmp_path)
    rc, _ = run(args(images, tmp_path, "readback", *extra), board)
    assert rc == 0
    return [r for sub, r, _d in board.runs if sub == "readback"][0]


def test_readback_request_puts_mount_and_output_under_run_not_the_state_dir(images, tmp_path):
    req = _readback_request(images, tmp_path, "--run-id", "rb-1")
    assert req["run_id"] == "rb-1"
    assert "out_dir" not in req and "mount_dir" not in req, "the board derives its own directories"
    assert not READBACK_RUN_BASE.startswith(req["state_dir"])


def test_readback_generated_run_id_is_a_plain_readback_id(images, tmp_path):
    req = _readback_request(images, tmp_path)
    assert re.fullmatch(r"readback-[0-9a-f]{8}", req["run_id"])


def test_readback_with_a_disk_state_dir_still_reaches_the_mount_step(images, tmp_path):
    """The gate asks findmnt about the output directory; with the state dir on btrfs and /run on tmpfs the
    request the CLI builds must pass it (unit tests that fake the fstype globally could not see this)."""
    import posixpath
    from avocado_flash_remote import profile as prof
    from avocado_flash_remote.cmd_readback import run_readback
    from avocado_flash_remote.ops import RecordingOps

    req = _readback_request(images, tmp_path, "--run-id", "rb-1")
    profile = prof.load_profile_bytes((PROFILES / "jetson-agx-orin-j5012.json").read_bytes())
    disk, part = profile.target.device, "/dev/mmcblk0p16"
    mnt, out = f"{READBACK_RUN_BASE}/rb-1/mnt", f"{READBACK_RUN_BASE}/rb-1/readback"
    probe = posixpath.dirname(out)
    fstype = "btrfs\n" if probe.startswith(req["state_dir"]) else "tmpfs\n"
    script = {
        "efibootmgr -v": "BootCurrent: 0001\nBootOrder: 0001\nBoot0001* UEFI\n",
        "lsblk -dn -o NAME": "mmcblk0\n",
        f"lsblk {disk}": "NAME SIZE\nmmcblk0 58G\n",
        f"lsblk -rn -o NAME,PARTLABEL {disk}": "mmcblk0p16 DATAPART_EXPAND\n",
        f"findmnt -no FSTYPE -T {probe}": fstype,
        f"ls -la {mnt}": "total 0\n",
        f"ls -laR {mnt}/log/journal": "ok\n",
    }
    ops = RecordingOps(script)
    res = run_readback(
        ops, profile, mount_dir=mnt, out_dir=out, reference_boot_order="0001",
        copier=lambda s, d: None, list_logs=lambda m: [], out=lambda line: None,
        makedirs=lambda *a, **k: None, nearest_existing=posixpath.dirname,
    )
    assert any(x.startswith("mount") for x in ops.log), res.lines


def test_two_generated_readbacks_never_share_a_run_id_and_so_never_a_mount_directory(images, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = _readback_request(images, tmp_path / "a")
    second = _readback_request(images, tmp_path / "b")
    assert first["run_id"] != second["run_id"]
    assert re.fullmatch(r"readback-[0-9a-f]{8}", first["run_id"])


def test_readback_takes_the_per_host_lock_and_refuses_while_another_holds_it(images, tmp_path, board, capsys):
    rid = _stage_and_plan(images, tmp_path, board)
    lock_path = next((tmp_path / "ev").glob(".lock-*"), None)
    with HostLock(lock_path or (tmp_path / "ev" / ".lock-op_board.local"), HOST, "other"):
        rc, _ = run(args(images, tmp_path, "readback", "--reference-boot-order", "0001"), board)
    assert rc == 1
    assert "held by" in capsys.readouterr().err
    assert "readback" not in board.subs()


def test_write_does_not_print_complete_when_write_json_is_not_in_the_record_set(images, tmp_path, capsys):
    board = Board(tmp_path)
    rid = _stage_and_plan(images, tmp_path, board)
    board.omit_write_json = True
    rc, text = run(args(images, tmp_path, "write", "--run-id", rid), board)
    assert rc == 1
    assert "write COMPLETE" not in text
    assert "write.json" in capsys.readouterr().err


def test_write_does_not_print_complete_when_the_manifest_is_not_runner_complete(images, tmp_path, capsys):
    board = Board(tmp_path)
    rid = _stage_and_plan(images, tmp_path, board)
    board.write_run_status = "incomplete"
    rc, text = run(args(images, tmp_path, "write", "--run-id", rid), board)
    assert rc == 1
    assert "write COMPLETE" not in text
    assert "runner-complete" in capsys.readouterr().err


@pytest.mark.parametrize("sub", ["plan", "restore", "check", "status"])
def test_a_host_timeout_exits_with_the_dropped_connection_code_and_says_to_run_status(images, tmp_path, sub, capsys):
    board = Board(tmp_path)
    rid = _stage_and_plan(images, tmp_path, board)
    board.timeout_sub = sub
    extra = {"restore": ["--ack-run", rid, "--run-id", rid]}.get(sub, [])
    rc, _ = run(args(images, tmp_path, sub, *extra), board)
    err = capsys.readouterr().err
    assert rc == cli.EXIT_DROPPED
    assert "may have acted" in err and "status" in err


def _name_only_extension(tmp_path):
    ext = tmp_path / "ext"
    ext.mkdir()
    doc = json.loads((PROFILES / "fixture-none.json").read_bytes())
    doc["target"]["identity"] = {"kind": "sysfs-name", "value": "loop-fixture"}
    doc["checks"] = [c for c in doc["checks"] if c != "target-identity"]
    (ext / "fixture-none.json").write_text(json.dumps(doc))
    return ext


def test_write_refuses_name_only_identity_before_the_retype_prompt(images, tmp_path, board, capsys):
    ext = _name_only_extension(tmp_path)
    a = args(images, tmp_path, "stage", "--extension-dir", str(ext))
    assert run(a, board)[0] == 0
    assert run(args(images, tmp_path, "plan", "--extension-dir", str(ext)), board)[0] == 0
    rid = plan_run_id(tmp_path)

    def boom(prompt):
        raise AssertionError("the retype prompt must not appear")

    rc, text = run(args(images, tmp_path, "write", "--run-id", rid, "--extension-dir", str(ext)), board, confirm=boom)
    assert rc == 1
    err = capsys.readouterr().err + text
    assert "target-identity" in err and "serial" in err
    assert "write" not in board.subs()


def test_check_and_plan_keep_running_on_a_name_only_profile(images, tmp_path, board):
    ext = _name_only_extension(tmp_path)
    assert run(args(images, tmp_path, "stage", "--extension-dir", str(ext)), board)[0] == 0
    assert run(args(images, tmp_path, "check", "--extension-dir", str(ext)), board)[0] == 0
    assert run(args(images, tmp_path, "plan", "--extension-dir", str(ext)), board)[0] == 0


# --- 5.41: the staged runner is this tool's build; a network failure is not a missing bundle ---------

STALE_BUILD = "staged runner is from a different tool build"


@pytest.mark.parametrize("sub", ["check", "plan", "write", "readback", "restore"])
def test_a_staged_bundle_from_a_different_build_is_refused_before_any_runner_call(images, tmp_path, sub, capsys):
    board, rid = _prepared(images, tmp_path)
    board.bundle_sha = "f" * 64
    board.runs.clear()
    board.requests.clear()
    capsys.readouterr()
    rc, _ = run(_sub_args(images, tmp_path, sub, rid), board)
    assert rc == 1
    assert STALE_BUILD in capsys.readouterr().err
    assert board.runs == [] and board.requests == {}


@pytest.mark.parametrize(
    "shape",
    [{"bundle_hash_rc": 1}, {"bundle_hash_rc": 127}, {"bundle_sha": "not-a-digest"}, {"bundle_sha": "F" * 63}],
    ids=["sha256sum-fails", "sha256sum-absent", "unparseable", "too-short"],
)
def test_an_unreadable_staged_bundle_hash_fails_closed_with_the_stage_again_message(images, tmp_path, shape, capsys):
    board, rid = _prepared(images, tmp_path)
    for key, value in shape.items():
        setattr(board, key, value)
    board.runs.clear()
    capsys.readouterr()
    rc, _ = run(_sub_args(images, tmp_path, "check", rid), board)
    assert rc == 1
    assert "run stage again" in capsys.readouterr().err
    assert board.runs == []


def test_a_matching_staged_bundle_proceeds_and_the_hash_probe_is_unprivileged(images, tmp_path):
    board, rid = _prepared(images, tmp_path)
    board.stub.calls.clear()
    rc, text = run(_sub_args(images, tmp_path, "check", rid), board)
    assert rc == 0, text
    probes = [c for c in board.stub.calls if c.argv[:1] == ["sha256sum"]]
    assert len(probes) == 1 and probes[0].sudo is False
    assert probes[0].argv[-1] == "/run/fixture-images/runner.pyz"


def test_status_stays_available_when_the_staged_build_differs(images, tmp_path):
    board, rid = _prepared(images, tmp_path)
    board.bundle_sha = "f" * 64
    rc, _ = run(_sub_args(images, tmp_path, "status", rid), board)
    assert rc == 0
    assert "status" in board.subs()


@pytest.mark.parametrize("where", ["test", "id", "sudo"])
def test_an_ssh_failure_while_connecting_is_a_dropped_connection_not_a_missing_bundle_or_a_prompt(
    images, tmp_path, where, capsys
):
    board, rid = _prepared(images, tmp_path)
    board.unreachable_at = where
    asked = []
    board.runs.clear()
    capsys.readouterr()
    rc, _ = run(args(images, tmp_path, "check"), board, ask_password=lambda: asked.append(1) or PASSWORD)
    err = capsys.readouterr().err
    assert rc == 2
    assert "cannot reach the board over ssh" in err
    assert "not on the board" not in err
    assert asked == []
    assert board.runs == []


def test_plan_ssh_failure_exits_2_and_keeps_the_local_run_dir(images, tmp_path, capsys):
    board = Board(tmp_path)
    assert run(args(images, tmp_path, "stage"), board)[0] == 0
    orig = board._runner

    def dropped(argv):
        if argv[2] == "plan":
            return RunResult(255, b"", b"ssh: connection reset")
        return orig(argv)

    board._runner = dropped
    rc, _ = run(args(images, tmp_path, "plan"), board)
    assert rc == 2
    assert "status" in capsys.readouterr().err
    assert [p for p in (tmp_path / "ev").iterdir() if p.is_dir()]


# --- a rebuilt host tool can re-stage only the runner and then restore ---------------------

RESTAGE_CMD = f"avocado-flash ssh-emmc stage --runner-only --board fixture-none --host {HOST}"


def _runner_only_args(tmp_path, *extra):
    return ["stage", "--runner-only", "--board", "fixture-none", "--host", HOST, "--evidence-dir", str(tmp_path / "ev"), *extra]


@pytest.mark.parametrize("restore_extra", [["--ack-run", "run-x"], ["--emergency-disarm", "--ack-run", "run-x"]], ids=["restore", "disarm"])
def test_a_rebuilt_tool_refuses_restore_naming_the_runner_only_restage_which_then_unblocks_it(
    images, tmp_path, restore_extra, capsys
):
    board, _rid = _prepared(images, tmp_path)
    board.bundle_sha = "f" * 64  # the staged runner is from an older tool build
    board.runs.clear()
    capsys.readouterr()
    restore = ["restore", "--board", "fixture-none", "--host", HOST, "--evidence-dir", str(tmp_path / "ev"), *restore_extra]
    rc, _ = run(restore, board)
    assert rc == 1
    assert "staged runner is from a different tool build" in capsys.readouterr().err
    assert board.runs == []
    board.bundle_sha = None  # the board now reports what the host copies
    board.stub.calls.clear()
    rc, text = run(_runner_only_args(tmp_path), board)
    assert rc == 0, text
    (tar,) = [c for c in board.stub.calls if c.kind == "put_tar"]
    assert sorted(tar.files) == sorted([cli.BUNDLE_NAME, "profile.json", ".avocado-flash-staging"])
    assert tar.modes[cli.BUNDLE_NAME] == 0o755 and tar.modes[".avocado-flash-staging"] == 0o644
    rc, text = run(restore, board)
    assert rc == 0, text
    assert board.subs()[-1] == "restore"


def test_the_stale_build_refusal_names_the_exact_runner_only_command(images, tmp_path, capsys):
    board, rid = _prepared(images, tmp_path)
    board.bundle_sha = "f" * 64
    capsys.readouterr()
    rc, _ = run(_sub_args(images, tmp_path, "restore", rid), board)
    assert rc == 1
    assert f"run `{RESTAGE_CMD}`" in capsys.readouterr().err


def test_runner_only_needs_no_images_directory_and_copies_no_image(images, tmp_path):
    board = Board(tmp_path)
    rc, text = run(_runner_only_args(tmp_path), board)
    assert rc == 0, text
    (tar,) = [c for c in board.stub.calls if c.kind == "put_tar"]
    assert not {"boot.img", "esp.img", "data.img", "MANIFEST.hashes"} & set(tar.files)


def test_runner_only_dry_run_is_offline_and_lists_only_the_runner_files(tmp_path):
    rc, text = run(["stage", "--runner-only", "--dry-run", "--board", "fixture-none", "--evidence-dir", str(tmp_path / "ev")])
    assert rc == 0
    assert cli.BUNDLE_NAME in text and "profile.json" in text and "boot.img" not in text


def test_runner_only_is_a_stage_option_and_takes_no_images(images, tmp_path, capsys):
    board = Board(tmp_path)
    rc, _ = run(args(images, tmp_path, "check", "--runner-only"), board)
    assert rc == 64
    assert "--runner-only" in capsys.readouterr().err
    rc, _ = run(args(images, tmp_path, "stage", "--runner-only"), board)
    assert rc == 64
    assert "--images" in capsys.readouterr().err
