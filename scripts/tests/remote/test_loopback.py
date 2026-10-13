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
import shutil
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


def _assert_no_sudo_was_spawned(transport):
    """Judge the argv command_line returned (what would be executed), and prove a wrapper was actually removed."""
    assert transport.spawned
    assert transport.stripped_sudo > 0, "no sudo wrapper was ever asked for, so 'never spawned' proves nothing"
    assert all(c[0] != "sudo" for c in transport.spawned), [c for c in transport.spawned if c[0] == "sudo"]


def test_the_sudo_assertion_fails_against_a_transport_that_forgets_to_strip_the_wrapper(board):
    class Broken(loopback.LoopbackTransport):
        def _command_line(self, remote_argv):
            super()._command_line(remote_argv)
            return list(remote_argv)  # hands the sudo wrapper straight to the spawn

    broken = Broken(board.root)
    broken.command_line(["sudo", "-n", "true"])
    with pytest.raises(AssertionError):
        _assert_no_sudo_was_spawned(broken)
    assert broken.spawned == [["sudo", "-n", "true"]]


def test_the_sudo_assertion_fails_when_no_wrapper_was_ever_requested(board):
    unused = loopback.LoopbackTransport(board.root)
    unused.command_line(["true"])
    with pytest.raises(AssertionError, match="proves nothing"):
        _assert_no_sudo_was_spawned(unused)


def test_the_loopback_never_runs_sudo_or_touches_a_path_outside_its_root(board):
    rid = _planned(board)
    board.cli("write", "--run-id", rid)
    assert board.transport.calls
    _assert_no_sudo_was_spawned(board.transport)
    with pytest.raises(host.HostError, match="outside the loopback root"):
        board.transport.run(["cat", "/etc/hostname"], None, sudo=False)


def test_the_loopback_refuses_a_sudo_password_stream(board):
    # SSH transport sudo password setter, not a Django account password; never stored.
    # nosemgrep: python.django.security.audit.unvalidated-password.unvalidated-password
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


# ------------------------------------------------------- 5.25: the board must be able to catch a bad write


def _loop_ops(board):
    import loopback_ops

    return loopback_ops.LoopOps(board.root)


def _stage_image(board, number):
    ops = _loop_ops(board)
    # Stage the board root the way the host does so LoopOps can read the images it is asked to write.
    board.stage.mkdir(exist_ok=True)
    for name in loopback.IMAGE_NAMES:
        shutil.copy(board.images / name, board.stage / name)
    return ops, board.stage / ops.images[number]


def test_loopops_answers_a_readback_from_what_was_written_to_that_partition(board):
    import loopback_ops

    ops, src = _stage_image(board, 1)
    ops._exec(["sfdisk", loopback_ops.DEVICE], stdin=b"x")
    ops._exec(["dd", f"if={src}", f"of={loopback_ops.DEVICE}1", "bs=1M", "conv=fsync", "status=none"])
    good = ops._exec(["dd", f"if={loopback_ops.DEVICE}1", "bs=4M", "iflag=count_bytes", f"count={src.stat().st_size}", "status=none"], digest=True)
    assert good.digest == ops._image_sha(1)


@pytest.mark.parametrize(
    "tail",
    [["--delete", "{dev}", "1"], ["--force", "{dev}"], ["{dev}", "extra"], ["--wipe", "always", "{dev}"]],
    ids=["delete", "force", "extra-arg", "wipe"],
)
def test_loopops_takes_only_the_exact_table_write_as_a_partition_table(board, tail):
    import loopback_ops

    ops = _loop_ops(board)
    vec = ["sfdisk", *[a.format(dev=loopback_ops.DEVICE) for a in tail]]
    with pytest.raises(loopback_ops.UnscriptedCall):
        ops._exec(vec, stdin=b"x")
    assert ops.partitioned is False and ops.sfdisk_input == b""


def test_loopops_readback_of_an_unwritten_partition_is_not_the_images_hash(board):
    import loopback_ops

    ops, _src = _stage_image(board, 1)
    got = ops._exec(["dd", f"if={loopback_ops.DEVICE}1", "bs=4M", "status=none"], digest=True)
    assert got.digest != ops._image_sha(1)


def test_loopops_readback_of_a_partition_given_another_partitions_image_differs(board):
    import loopback_ops

    ops, src = _stage_image(board, 1)
    ops._exec(["sfdisk", loopback_ops.DEVICE], stdin=b"x")
    ops._exec(["dd", f"if={src}", f"of={loopback_ops.DEVICE}2", "bs=1M", "conv=fsync", "status=none"])
    got = ops._exec(["dd", f"if={loopback_ops.DEVICE}2", "bs=4M", "status=none"], digest=True)
    assert got.digest != ops._image_sha(2)


def test_loopops_refuses_a_dd_before_the_partition_table_exists(board):
    import loopback_ops
    from avocado_flash_remote.ops import UnscriptedCall

    ops, src = _stage_image(board, 1)
    with pytest.raises(UnscriptedCall, match="no partition table"):
        ops._exec(["dd", f"if={src}", f"of={loopback_ops.DEVICE}1", "bs=1M", "conv=fsync", "status=none"])


def test_loopops_refuses_a_dd_to_a_node_that_is_not_a_partition_of_the_table(board):
    import loopback_ops
    from avocado_flash_remote.ops import UnscriptedCall

    ops, src = _stage_image(board, 1)
    ops._exec(["sfdisk", loopback_ops.DEVICE], stdin=b"x")
    for node in (loopback_ops.DEVICE, f"{loopback_ops.DEVICE}9"):
        with pytest.raises(UnscriptedCall):
            ops._exec(["dd", f"if={src}", f"of={node}", "bs=1M", "conv=fsync", "status=none"])


def test_loopops_raises_on_an_unscripted_mutating_command(board):
    from avocado_flash_remote.ops import UnscriptedCall

    ops = _loop_ops(board)
    with pytest.raises(UnscriptedCall):
        ops._exec(["wipefs", "-a", "/dev/vdz"])


def test_loopops_sfdisk_dump_returns_what_sfdisk_was_given_not_the_expected_layout(board):
    import loopback_ops

    ops = _loop_ops(board)
    ops._exec(["sfdisk", loopback_ops.DEVICE], stdin=b"label: gpt\nother\n")
    assert ops._exec(["sfdisk", "--dump", loopback_ops.DEVICE]).stdout == b"label: gpt\nother\n"


def test_a_skipped_dd_is_caught_by_the_write(board):
    rid = _planned(board)
    board.inject("skip-dd", "2")  # the runner is told the dd succeeded; nothing reaches partition 2
    rc, text, err = board.cli("write", "--run-id", rid)
    assert rc != 0, text + err
    assert "write COMPLETE" not in text
    assert "does not match the planned checksum" in text, text


def test_a_dd_sent_to_the_wrong_partition_is_caught_by_the_write(board):
    rid = _planned(board)
    board.inject("misdirect-dd", "1:2")  # the image for partition 1 lands on partition 2
    rc, text, err = board.cli("write", "--run-id", rid)
    assert rc != 0, text + err
    assert "write COMPLETE" not in text
    assert "readback of /dev/vdz1" in text and "does not match the planned checksum" in text, text


def test_a_write_that_never_created_the_table_is_caught(board):
    rid = _planned(board)
    board.inject("skip-sfdisk", "1")
    rc, text, err = board.cli("write", "--run-id", rid)
    assert rc != 0, text + err
    assert "write COMPLETE" not in text
    assert "writing boot.img" not in text, text  # no image is written onto a disk with no table


# ---- a missing runtime directory is a failure, not a silent skip of the whole file ----


def test_a_missing_runtime_directory_fails_loudly_and_names_the_opt_out(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.delenv(loopback.SKIP_ENV, raising=False)
    with pytest.raises(pytest.fail.Exception) as ei:
        loopback.LoopbackBoard(tmp_path)
    assert "XDG_RUNTIME_DIR" in str(ei.value) and loopback.SKIP_ENV in str(ei.value)


def test_the_opt_out_variable_turns_the_missing_runtime_directory_into_a_skip(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setenv(loopback.SKIP_ENV, "1")
    with pytest.raises(pytest.skip.Exception) as ei:
        loopback.LoopbackBoard(tmp_path)
    assert loopback.SKIP_ENV in str(ei.value)
