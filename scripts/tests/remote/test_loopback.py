"""Host and runner together, end to end (task 5.23).

``cli.main`` talks to a ``LoopbackTransport`` that executes every command line
locally, running the real ``runner.pyz`` built by ``bundle.build_bundle`` in a
separate process. Nothing in the markers or the request is written by a test,
so a disagreement between what the runner writes and what the host parses
shows up here and nowhere in the stub-board suites.
"""

from __future__ import annotations

import json
import os
import signal

import pytest

import loopback
from avocado_flash_remote import host


@pytest.fixture
def board(tmp_path):
    b = loopback.LoopbackBoard(tmp_path)
    yield b
    b.release()
    b.reap()


def _planned(board):
    assert board.cli("stage")[0] == 0
    rc, text, err = board.cli("plan")
    assert rc == 0, text + err
    return board.plan_run_id()


def test_a_clean_plan_then_write_completes_with_the_nonce_the_runner_wrote(board):
    rid = _planned(board)
    rc, text, err = board.cli("write", "--run-id", rid)
    assert rc == 0, text + err
    assert f"write COMPLETE (run {rid})" in text
    accepted = board.marker(rid, "accepted").split("\n")
    outcome = board.marker(rid, "outcome").split("\n")
    nonce = board.last_request("write")["invocation_nonce"]
    assert accepted[1] == f"nonce={nonce}"
    assert outcome[:3] == ["finished", f"run={rid}", f"nonce={nonce}"]
    # The runner's own pid is on the first line, as the host's dead-runner probe expects.
    assert accepted[0].isdigit()


def test_complete_depends_on_the_runner_marker_nonce_not_on_the_phase_alone(board):
    rid = _planned(board)
    board.hold()

    def another_invocation_takes_the_marker(_secs):
        # Replace the runner's accepted marker the way a second invocation's runner would,
        # while the real runner is still inside its write.
        assert board.wait_in_dd()
        path = board.run_dir(rid) / "accepted"
        runner_pid = path.read_text().split("\n")[0]
        path.write_text(f"{runner_pid}\nnonce={'ab' * 8}\n")
        board.release()

    rc, text, _err = board.cli("write", "--run-id", rid, sleep=another_invocation_takes_the_marker)
    assert rc == 1
    assert "write COMPLETE" not in text
    assert "did not write it" in text


def test_a_second_write_started_while_the_first_is_inside_its_write_is_refused(board, tmp_path, capsys):
    rid = _planned(board)
    board.hold()
    seen = {}

    def second_workstation(_secs):
        if seen:
            return
        assert board.wait_in_dd(), "the first runner never reached its write"
        before = board.snapshot(rid)
        other_ev = tmp_path / "ev2"
        board.copy_plan(rid, other_ev)
        capsys.readouterr()
        rc, text, err = board.cli("write", "--run-id", rid, evidence=other_ev)
        seen.update(rc=rc, text=text, err=err, before=before, after=board.snapshot(rid))
        board.release()

    rc, text, _err = board.cli("write", "--run-id", rid, sleep=second_workstation)
    assert seen, "the second write never ran"
    assert seen["rc"] != 0
    both = seen["text"] + seen["err"]
    assert "write COMPLETE" not in both
    # While the first runner is inside dd the board IS changing: the refusal must say so, and must
    # never claim that nothing was written.
    assert "nothing was written to the board" not in both
    assert "already in progress" in both and "the board may be changing" in both and "status" in both
    assert seen["before"] == seen["after"], "the refused invocation touched the first runner's records"
    assert seen["before"]["accepted"] and seen["before"]["MANIFEST.json"]
    # The first write is unaffected and still finishes by itself.
    assert rc == 0 and "write COMPLETE" in text


def test_a_replayed_completed_run_exits_nonzero_without_complete(board):
    rid = _planned(board)
    assert board.cli("write", "--run-id", rid)[0] == 0
    before = board.snapshot(rid)
    rc, text, err = board.cli("write", "--run-id", rid)
    assert rc != 0
    assert "write COMPLETE" not in text + err
    assert board.snapshot(rid) == before
    # The run already wrote to the board; the refusal never calls the board unchanged.
    assert "nothing was written to the board" not in text + err
    assert "already has a state record" in text + err


def test_a_runner_killed_after_accepted_is_a_dead_runner_not_complete(board):
    rid = _planned(board)
    board.hold()
    killed = {}

    def kill_the_runner(_secs):
        if killed:
            return
        assert board.wait_in_dd(), "the runner never reached its write"
        pid = int(board.marker(rid, "accepted").split("\n")[0])
        os.kill(pid, signal.SIGKILL)  # the runner this test started, by pid
        assert loopback.wait_until(lambda: not os.path.exists(f"/proc/{pid}") or loopback.is_zombie(pid))
        killed["pid"] = pid

    rc, text, _err = board.cli("write", "--run-id", rid, "--wait-seconds", "30", sleep=kill_the_runner)
    assert killed
    assert rc == 1
    assert "write COMPLETE" not in text
    assert "the runner exited while the board is still recorded in the non-terminal phase image-writing" in text


def test_the_loopback_never_runs_sudo_or_touches_a_path_outside_its_root(board):
    rid = _planned(board)
    board.cli("write", "--run-id", rid)
    assert board.transport.calls
    assert all(c[0] != "sudo" for c in board.transport.calls)
    with pytest.raises(host.HostError, match="outside the loopback root"):
        board.transport.run(["cat", "/etc/hostname"], None, sudo=False)


def test_the_loopback_refuses_a_sudo_password_stream(board):
    board.transport.set_password(host.Secret("x"))
    with pytest.raises(host.HostError, match="password sudo"):
        board.transport.run(["true"], None, sudo=True)


def test_the_request_files_are_named_by_nonce_and_none_is_left_behind(board):
    rid = _planned(board)
    assert board.cli("write", "--run-id", rid)[0] == 0
    nonce = board.last_request("write")["invocation_nonce"]
    sent = [p for p, _body in board.transport.requests if "request-write" in p]
    assert sent == [f"{board.stage}/request-write-{nonce}.json"]
    assert sorted(p.name for p in board.stage.glob("request-*")) == []


def test_a_runner_that_cannot_record_acceptance_does_no_work_and_the_host_does_not_complete(board):
    rid = _planned(board)
    board.fail_accepted_writes()
    rc, text, err = board.cli("write", "--run-id", rid)
    assert rc == 1
    assert "write COMPLETE" not in text + err
    # COMPLETE depends on the marker, so the runner stops before any work: no state, no write, no outcome.
    assert not (board.state / rid / "state.json").exists()
    assert not (board.run_dir(rid) / "accepted").exists()
    assert "cannot write accepted marker" in (board.run_dir(rid) / "runner.log").read_text()
    assert "the write did not start" in text


def test_a_completed_write_is_judged_by_its_own_state_even_after_another_run_moved_current(board):
    rid = _planned(board)
    board.hold()
    moved = {}

    def another_run_creates_its_state(_secs):
        if moved:
            return
        assert board.wait_in_dd()
        board.release()
        assert loopback.wait_until(lambda: (board.run_dir(rid) / "outcome").exists())
        # Run B's create_run lands after A completed and before A's host polls again.
        other = board.state / "run-B"
        other.mkdir()
        data = json.loads((board.state / rid / "state.json").read_text())
        data.update(run_id="run-B", phase="planned")
        (other / "state.json").write_text(json.dumps(data))
        (board.state / "current").write_text("run-B\n")
        moved["done"] = True

    rc, text, err = board.cli("write", "--run-id", rid, sleep=another_run_creates_its_state)
    assert moved
    assert "the board may have been changed" not in text + err
    assert rc == 0 and f"write COMPLETE (run {rid})" in text
