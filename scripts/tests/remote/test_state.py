"""Durable state machine and lock tests (task 3.3)."""

from __future__ import annotations

import fcntl
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

import pytest

from avocado_flash_remote import state as st

ROLES = ["boot", "rootfs"]


def _new(tmp_path, arm=True):
    return st.create_run(
        tmp_path,
        run_id="run-1",
        profile_hash="p" * 8,
        plan_hash="q" * 8,
        board_identity={"serial": "abc"},
        image_roles=ROLES,
        arm=arm,
    )


def _table_written(s):
    s = st.transition(s, "table-writing")
    return st.transition(s, "table-written")


def _walk_to_verified(s):
    s = _table_written(s)
    for role in ROLES:
        s = st.transition(s, "image-writing", image=role)
        s = st.transition(
            s,
            "image-written",
            image=role,
            bytes_written=10,
            expected_sha256="a" * 64,
            readback_sha256="a" * 64,
        )
    return st.transition(s, "verified")


def _read(tmp_path):
    r = st.load_state(tmp_path)
    assert r.status == "ok", r
    return r.state


# ---- transitions -----------------------------------------------------


def test_full_happy_path_with_arm(tmp_path):
    s = _walk_to_verified(_new(tmp_path))
    s = st.transition(s, "armed", armed={
        "entry_number": "0001", "label": "avocado",
        "preexisting_boot_order": "0002,0003", "preexisting_next": None})
    s = st.transition(s, "complete")
    on_disk = _read(tmp_path)
    assert on_disk.phase == "complete"
    assert on_disk.data["armed"]["entry_number"] == "0001"
    seqs = [e["seq"] for e in on_disk.data["phases_done"]]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert on_disk.data["images"]["rootfs"]["readback_sha256"] == "a" * 64
    assert on_disk.data["images"]["rootfs"]["bytes_written"] == 10
    assert (tmp_path / "current").read_text().strip() == "run-1"


def test_no_arm_goes_verified_to_complete(tmp_path):
    s = _walk_to_verified(_new(tmp_path, arm=False))
    with pytest.raises(st.IllegalTransition):
        st.transition(s, "armed")
    assert st.transition(s, "complete").phase == "complete"


def test_arm_required_when_enabled(tmp_path):
    s = _walk_to_verified(_new(tmp_path, arm=True))
    with pytest.raises(st.IllegalTransition):
        st.transition(s, "complete")


@pytest.mark.parametrize(
    "target", ["table-written", "image-writing", "verified", "armed", "complete", "planned"]
)
def test_no_skipping_from_planned(tmp_path, target):
    s = _new(tmp_path)
    with pytest.raises(st.IllegalTransition):
        st.transition(s, target, image="boot")


def test_no_going_back(tmp_path):
    s = _table_written(_new(tmp_path))
    with pytest.raises(st.IllegalTransition):
        st.transition(s, "planned")


def test_images_in_profile_order_and_all_required(tmp_path):
    s = _table_written(_new(tmp_path))
    with pytest.raises(st.IllegalTransition):
        st.transition(s, "image-writing", image="rootfs")
    with pytest.raises(st.IllegalTransition):
        st.transition(s, "verified")
    s = st.transition(s, "image-writing", image="boot")
    with pytest.raises(st.IllegalTransition):
        st.transition(s, "image-written", image="rootfs")


def test_terminal_states_are_final_and_failed_from_anywhere(tmp_path):
    s = _table_written(_new(tmp_path))
    s = st.transition(s, "failed", error="boom")
    assert _read(tmp_path).data["error"] == "boom"
    with pytest.raises(st.IllegalTransition):
        st.transition(s, "complete")
    with pytest.raises(st.IllegalTransition):
        st.transition(s, "failed")


def test_table_writing_sits_between_planned_and_table_written(tmp_path):
    s = st.transition(_new(tmp_path), "table-writing")
    assert _read(tmp_path).phase == "table-writing"
    for target in ("planned", "table-writing", "image-writing", "verified"):
        with pytest.raises(st.IllegalTransition):
            st.transition(s, target, image="boot")
    assert st.transition(s, "table-written").phase == "table-written"
    s2 = st.transition(_table_written(_new(tmp_path / "x")), "failed", error="e")
    with pytest.raises(st.IllegalTransition):
        st.transition(s2, "table-writing")


def test_cannot_go_back_to_table_writing(tmp_path):
    s = _table_written(_new(tmp_path))
    with pytest.raises(st.IllegalTransition):
        st.transition(s, "table-writing")


def test_table_writing_may_fail(tmp_path):
    s = st.transition(_new(tmp_path), "table-writing")
    assert st.transition(s, "failed", error="x").phase == "failed"


def test_table_writing_rerun_refusal_prints_restore_then_restart(tmp_path):
    st.transition(_new(tmp_path), "table-writing")
    with pytest.raises(st.RerunRefused) as ei:
        st.check_rerun_allowed(tmp_path)
    msg = str(ei.value)
    assert "table-writing" in msg and "restore-then-restart" in msg
    assert st.RECOVERY["table-writing"] == "restore-then-restart"
    assert "re-inspect" in st.describe_recovery(_read(tmp_path))


def test_planned_recovery_says_nothing_recorded_not_nothing_written(tmp_path):
    text = st.describe_recovery(_new(tmp_path))
    assert "no board change has been recorded" in text
    assert "lock" in text
    assert "nothing was written" not in text


def test_failed_from_planned(tmp_path):
    assert st.transition(_new(tmp_path), "failed", error="x").phase == "failed"


# ---- crash injection --------------------------------------------------

POINTS = ["before-write", "after-temp-write", "after-fsync", "after-rename"]


class Boom(BaseException):
    pass


def _transitions(s):
    """Yield (name, callable) for every transition of the arm path."""
    yield "table-writing", lambda s: st.transition(s, "table-writing")
    yield "table-written", lambda s: st.transition(s, "table-written")
    for role in ROLES:
        yield f"writing-{role}", lambda s, r=role: st.transition(s, "image-writing", image=r)
        yield f"written-{role}", lambda s, r=role: st.transition(
            s, "image-written", image=r, bytes_written=1,
            expected_sha256="b" * 64, readback_sha256="b" * 64)
    yield "verified", lambda s: st.transition(s, "verified")
    yield "armed", lambda s: st.transition(s, "armed", armed={
        "entry_number": "0001", "label": "l",
        "preexisting_boot_order": None, "preexisting_next": None})
    yield "complete", lambda s: st.transition(s, "complete")


@pytest.mark.parametrize("point", POINTS)
def test_kill_between_every_phase_leaves_parseable_file(tmp_path, monkeypatch, point):
    s = _new(tmp_path)
    steps = list(_transitions(s))
    for i, (name, fn) in enumerate(steps):
        before = _read(tmp_path)
        before_seq = before.data["seq"]
        hit = {"n": 0}

        def fault(p, hit=hit):
            if p == point:
                hit["n"] += 1
                raise Boom(p)

        monkeypatch.setattr(st, "_fault", fault)
        with pytest.raises(Boom):
            fn(s)
        monkeypatch.setattr(st, "_fault", lambda p: None)
        assert hit["n"] >= 1
        after = _read(tmp_path)  # always parseable
        if point == "after-rename":
            assert after.data["seq"] == before_seq + 1, name
        else:
            assert after.data["seq"] == before_seq, name
            assert after.phase == before.phase, name
        # recover in-memory view from disk and continue the walk
        s = after if point == "after-rename" else fn(after)
    assert _read(tmp_path).phase == "complete"


def test_crash_during_create_never_leaves_partial_pointer(tmp_path, monkeypatch):
    def fault(p):
        if p == "after-temp-write":
            raise Boom(p)

    monkeypatch.setattr(st, "_fault", fault)
    with pytest.raises(Boom):
        _new(tmp_path)
    monkeypatch.setattr(st, "_fault", lambda p: None)
    assert st.load_state(tmp_path).status in ("absent", "ok")


# ---- load / rerun -----------------------------------------------------


def test_load_absent(tmp_path):
    assert st.load_state(tmp_path).status == "absent"
    st.check_rerun_allowed(tmp_path)


def test_terminal_allows_plain_rerun(tmp_path):
    s = st.transition(_new(tmp_path), "failed", error="e")
    d = st.check_rerun_allowed(tmp_path)
    assert d.recovery_only is False
    assert s.phase == "failed"


def test_corrupt_file_is_unparseable_and_refuses(tmp_path):
    _new(tmp_path)
    (tmp_path / "run-1" / "state.json").write_text("{not json")
    r = st.load_state(tmp_path)
    assert r.status == "unparseable" and r.reason
    with pytest.raises(st.RerunRefused) as ei:
        st.check_rerun_allowed(tmp_path)
    assert "run-1" in str(ei.value)
    assert r.reason in str(ei.value)


def test_truncated_and_wrong_schema_unparseable(tmp_path):
    _new(tmp_path)
    p = tmp_path / "run-1" / "state.json"
    p.write_text(json.dumps({"schema_version": 999}))
    assert st.load_state(tmp_path).status == "unparseable"
    p.write_text(json.dumps({"schema_version": 1, "phase": "bogus"}))
    assert st.load_state(tmp_path).status == "unparseable"
    p.unlink()
    assert st.load_state(tmp_path).status == "unparseable"


def test_nonterminal_refuses_with_phase_run_and_recovery(tmp_path):
    s = _walk_to_verified(_new(tmp_path))
    s = st.transition(s, "armed", armed={
        "entry_number": "0001", "label": "l",
        "preexisting_boot_order": "1", "preexisting_next": None})
    with pytest.raises(st.RerunRefused) as ei:
        st.check_rerun_allowed(tmp_path)
    msg = str(ei.value)
    assert "armed" in msg and "run-1" in msg
    assert "restore" in msg
    assert st.RECOVERY["armed"] == "restore"
    assert "restore" in st.describe_recovery(s)


def test_ack_enables_recovery_not_plain_rerun(tmp_path):
    _new(tmp_path)
    with pytest.raises(st.RerunRefused):
        st.check_rerun_allowed(tmp_path, ack_run_id="other")
    d = st.check_rerun_allowed(tmp_path, ack_run_id="run-1")
    assert d.recovery_only is True


def test_ack_for_unparseable(tmp_path):
    _new(tmp_path)
    (tmp_path / "run-1" / "state.json").write_text("garbage")
    d = st.check_rerun_allowed(tmp_path, ack_run_id="run-1")
    assert d.recovery_only is True


def test_recovery_table_one_action_per_nonterminal_phase():
    assert set(st.RECOVERY) == set(st.PHASES) - set(st.TERMINAL)
    assert all(isinstance(v, str) and v for v in st.RECOVERY.values())
    assert st.RECOVERY["verified"] == "restore"
    assert st.RECOVERY["planned"] == "none-recorded"


# ---- locks ---------------------------------------------------------------

HOLDER = """
import sys, time, pathlib
sys.path.insert(0, sys.argv[1])
from avocado_flash_remote import state as st
cls, path, ident, ready = sys.argv[2:6]
lock = st.OnBoardLock(path, run_id='holder-run') if cls == 'board' else st.HostLock(path, ident, run_id='holder-run')
lock.__enter__()
pathlib.Path(ready).write_text('ok')
time.sleep(60)
"""


def _start_holder(tmp_path, cls, lockpath, ident="hostA"):
    scripts = str(pathlib.Path(st.__file__).resolve().parents[1])
    ready = tmp_path / f"ready-{cls}"
    out = open(tmp_path / f"out-{cls}", "wb")
    p = subprocess.Popen(
        [sys.executable, "-c", HOLDER, scripts, cls, str(lockpath), ident, str(ready)],
        stdout=out, stderr=out, start_new_session=True)
    for _ in range(200):
        if ready.exists():
            return p
        time.sleep(0.05)
    _kill(p)
    pytest.fail((tmp_path / f"out-{cls}").read_text())


def _kill(p):
    if p.poll() is None and os.getpgid(p.pid) == p.pid:
        os.killpg(p.pid, signal.SIGKILL)
    p.wait()


@pytest.mark.parametrize("cls", ["board", "host"])
def test_second_writer_refused_and_released_on_holder_death(tmp_path, cls):
    path = tmp_path / "lock"

    def mk():
        if cls == "board":
            return st.OnBoardLock(path, run_id="mine")
        return st.HostLock(path, "hostA", run_id="mine")

    holder = _start_holder(tmp_path, cls, path)
    try:
        with pytest.raises(st.LockHeld) as ei:
            with mk():
                pass
        assert "holder-run" in str(ei.value)
        assert str(holder.pid) in str(ei.value)
    finally:
        _kill(holder)
    with mk():
        pass


def test_lock_released_on_exit_and_exclusive_in_process(tmp_path):
    path = tmp_path / "l"
    with st.OnBoardLock(path, run_id="a"):
        with pytest.raises(st.LockHeld):
            with st.OnBoardLock(path, run_id="b"):
                pass
    with st.OnBoardLock(path, run_id="c"):
        pass


def test_host_lock_names_host(tmp_path):
    path = tmp_path / "l"
    with st.HostLock(path, "board-7", run_id="a"):
        with pytest.raises(st.LockHeld) as ei:
            with st.HostLock(path, "board-7", run_id="b"):
                pass
    assert "board-7" in str(ei.value)


# ---- 5.15: recovery text is true, failed and restored are described ----------

import re as _re


def _no_bare_ack(text):
    return not _re.search(r"--ack(?!-run)", text)


@pytest.mark.parametrize("phase", ["table-writing", "table-written", "image-written", "verified", "armed"])
def test_recovery_text_names_the_real_flag_and_the_real_restore_scope(tmp_path, phase):
    s = _new(tmp_path)
    if phase in ("verified", "armed"):
        s = _walk_to_verified(s)
    else:
        s = st.transition(s, "table-writing")
        if phase != "table-writing":
            s = st.transition(s, "table-written")
    if phase == "armed":
        s = st.transition(s, "armed", armed={"entry_number": "0005"})
    text = st.describe_recovery(s)
    assert "--ack-run" in text and _no_bare_ack(text)
    assert "restore the saved partition table" not in text
    assert "restore the saved state" not in text


def test_rerun_refusal_mentions_the_ack_flag(tmp_path):
    st.transition(_new(tmp_path), "table-writing")
    with pytest.raises(st.RerunRefused) as ei:
        st.check_rerun_allowed(tmp_path)
    assert "--ack-run" in str(ei.value) and _no_bare_ack(str(ei.value))


def test_failed_recovery_is_not_no_recovery_needed(tmp_path):
    s = st.transition(_new(tmp_path), "table-writing")
    s = st.transition(s, "failed", error="sfdisk exploded")
    text = st.describe_recovery(s)
    assert "no recovery needed" not in text
    assert "sfdisk exploded" in text
    assert "partition table" in text and "possibly" in text
    assert "no boot entry" in text.lower()


def test_failed_recovery_names_partial_images_and_an_armed_entry(tmp_path):
    s = st.create_run(
        tmp_path, run_id="r1", profile_hash="p", plan_hash="q", board_identity={},
        image_roles=["boot", "root"], arm=True,
    )
    s = st.transition(s, "table-writing")
    s = st.transition(s, "table-written")
    s = st.transition(s, "image-writing", image="boot")
    s = st.transition(s, "image-written", image="boot", bytes_written=1, expected_sha256="a", readback_sha256="a")
    s = st.transition(s, "image-writing", image="root")
    clean = st.transition(s, "failed", error="dd failed")
    t1 = st.describe_recovery(clean)
    assert "root" in t1 and "partial" in t1 and "boot" in t1
    s2 = st.transition(
        st.create_run(
            tmp_path / "b", run_id="r2", profile_hash="p", plan_hash="q", board_identity={},
            image_roles=[], arm=True,
        ),
        "table-writing",
    )
    s2 = st.transition(s2, "table-written")
    s2 = st.transition(s2, "verified")
    s2 = st.transition(s2, "armed", armed={"entry_number": "0005", "next_armed": True})
    t2 = st.describe_recovery(st.transition(s2, "failed", error="late"))
    assert "armed" in t2 and "do not reboot" in t2.lower()


def test_restored_is_terminal_and_reachable_from_any_phase(tmp_path):
    assert "restored" in st.PHASES and "restored" in st.TERMINAL
    s = st.transition(_new(tmp_path), "table-writing")
    r = st.transition(s, "restored")
    assert r.phase == "restored"
    assert "no recovery needed" in st.describe_recovery(r)
    with pytest.raises(st.IllegalTransition):
        st.transition(r, "restored")
    f = st.transition(s, "failed", error="x")
    assert st.transition(f, "restored").phase == "restored"


# ---- 5.16: write-ahead arming phase ---------------------------------------------


def test_arming_sits_between_verified_and_armed(tmp_path):
    assert st.PHASES.index("verified") + 1 == st.PHASES.index("arming") == st.PHASES.index("armed") - 1
    s = _walk_to_verified(_new(tmp_path))
    s = st.transition(s, "arming", armed={"label": "x", "entry_number": ""})
    assert s.phase == "arming" and "arming" not in st.TERMINAL
    assert _read(tmp_path).data["armed"]["label"] == "x"
    s = st.transition(s, "arming", armed={"label": "x", "entry_number": "0005"})  # progress update
    assert _read(tmp_path).data["armed"]["entry_number"] == "0005"
    assert [e["phase"] for e in s.data["phases_done"]].count("arming") == 1
    assert st.transition(s, "armed", armed={"entry_number": "0005"}).phase == "armed"


def test_arming_needs_verified_and_arm_enabled(tmp_path):
    s = _table_written(_new(tmp_path))
    with pytest.raises(st.IllegalTransition):
        st.transition(s, "arming")
    s2 = _walk_to_verified(_new(tmp_path / "n", arm=False))
    with pytest.raises(st.IllegalTransition):
        st.transition(s2, "arming")


def test_arming_is_described_as_possibly_armed(tmp_path):
    s = st.transition(_walk_to_verified(_new(tmp_path)), "arming", armed={"label": "x"})
    text = st.describe_recovery(s)
    assert "DO NOT REBOOT" in text and "--ack-run run-1" in text
    assert "no recovery needed" not in text


# ---- 5.20: the recovery text must not promise a plan the shipped profile refuses ----


def _at_phase(tmp_path, phase):
    s = st.transition(_new(tmp_path), "table-writing")
    if phase == "table-writing":
        return s
    s = st.transition(s, "table-written")
    if phase == "table-written":
        return s
    s = st.transition(s, "image-writing", image="boot")
    if phase == "image-writing":
        return s
    return st.transition(
        s, "image-written", image="boot", bytes_written=1, expected_sha256="a", readback_sha256="a"
    )


@pytest.mark.parametrize("phase", ["table-writing", "table-written", "image-writing", "image-written"])
def test_restore_then_restart_names_the_manual_wipe_and_the_restage(tmp_path, phase):
    text = st.describe_recovery(_at_phase(tmp_path, phase))
    assert "from the start" not in text, text
    assert "wipe" in text and "stage" in text, text
    assert "require_empty" in text, text


def test_failed_after_table_write_names_the_wipe_and_the_restage(tmp_path):
    s = st.transition(_new(tmp_path), "table-writing")
    s = st.transition(s, "failed", error="boom")
    text = st.describe_recovery(s)
    assert "wipe" in text and "stage" in text and "require_empty" in text, text


def test_failed_before_the_table_was_touched_needs_no_wipe_but_still_a_restage(tmp_path):
    s = st.transition(_new(tmp_path), "failed", error="boom")
    text = st.describe_recovery(s)
    assert "by hand" not in text
    assert "stage" in text, text


def test_lock_wait_is_bounded_and_holder_is_reported(tmp_path):
    path = tmp_path / "lock"
    with st.OnBoardLock(path, run_id="holder"):
        t0 = time.monotonic()
        with pytest.raises(st.LockHeld) as ei:
            with st.OnBoardLock(path, run_id="waiter", wait_seconds=0.3):
                pass
        assert 0.25 <= time.monotonic() - t0 < 5
    assert json.loads(ei.value.holder)["pid"] == os.getpid()


def test_lock_wait_zero_refuses_without_waiting(tmp_path):
    path = tmp_path / "lock"
    with st.OnBoardLock(path, run_id="holder"):
        t0 = time.monotonic()
        with pytest.raises(st.LockHeld):
            with st.OnBoardLock(path, run_id="waiter"):
                pass
        assert time.monotonic() - t0 < 1


# ---- 5.25: a stale holder record is never shown as the holder


def test_a_released_on_board_lock_leaves_no_holder_record(tmp_path):
    path = tmp_path / "flash.lock"
    with st.OnBoardLock(path, run_id="a"):
        assert json.loads(path.read_text())["run_id"] == "a"
    assert path.read_text() == ""  # the last holder's pid must not outlive its hold


def test_a_record_that_changes_while_it_is_read_is_reported_as_an_unknown_holder(tmp_path, monkeypatch):
    path = tmp_path / "flash.lock"
    path.write_text(json.dumps({"pid": 999999999, "run_id": "old"}))
    holder_fh = open(path, "a+")
    fcntl.flock(holder_fh.fileno(), fcntl.LOCK_EX)  # a new writer already holds the lock but has not rewritten the record

    def new_writer_rewrites(_s):
        path.write_text(json.dumps({"pid": os.getpid(), "run_id": "new"}))

    monkeypatch.setattr(st.time, "sleep", new_writer_rewrites)
    try:
        with pytest.raises(st.LockHeld) as e:
            st.OnBoardLock(path, run_id="x").__enter__()
    finally:
        holder_fh.close()
    assert e.value.holder == ""  # the stale dead pid is not offered as the holder


# ---- schema-level validation: a state that parses but is inconsistent is unparseable ----


def _mutate(tmp_path, fn):
    s = _new(tmp_path)
    s = st.transition(s, "table-writing")
    path = tmp_path / "run-1" / "state.json"
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data))
    return path


def _set(key, value):
    def fn(d):
        d[key] = value

    return fn


def _drop(key):
    def fn(d):
        del d[key]

    return fn


BAD_STATES = {
    "run id other than the directory": _set("run_id", "run-2"),
    "run id with a separator": _set("run_id", "a/b"),
    "run id not a string": _set("run_id", 7),
    "seq zero": _set("seq", 0),
    "seq negative": _set("seq", -3),
    "seq a string": _set("seq", "2"),
    "seq a bool": _set("seq", True),
    "seq a float": _set("seq", 2.0),
    "arm_enabled not bool": _set("arm_enabled", "yes"),
    "image_order not a list": _set("image_order", "boot"),
    "image_order with a non-string": _set("image_order", ["boot", 3]),
    "phases_done not a list": _set("phases_done", {}),
    "phases_done entry not an object": _set("phases_done", ["planned"]),
    "phases_done unknown phase": _set("phases_done", [{"seq": 1, "phase": "bogus"}]),
    "images not a mapping": _set("images", []),
    "image state not an object": _set("images", {"boot": "pending", "rootfs": {"state": "pending"}}),
    "image with an unknown state": _set("images", {"boot": {"state": "done"}, "rootfs": {"state": "pending"}}),
    "ordered image missing from images": _set("images", {"boot": {"state": "pending"}}),
    "armed a string": _set("armed", "0005"),
    "armed with a non-string entry number": _set("armed", {"entry_number": 5}),
    "armed with a non-bool next_armed": _set("armed", {"next_armed": "true"}),
    "armed with an unknown key": _set("armed", {"entry_number": "0005", "evil": 1}),
    "missing phases_done": _drop("phases_done"),
}


@pytest.mark.parametrize("name", sorted(BAD_STATES))
def test_inconsistent_state_is_unparseable(tmp_path, name):
    _mutate(tmp_path, BAD_STATES[name])
    r = st.load_state(tmp_path)
    assert r.status == "unparseable", name
    assert r.reason


@pytest.mark.parametrize("name", sorted(BAD_STATES))
def test_inconsistent_state_blocks_rerun_without_ack(tmp_path, name):
    _mutate(tmp_path, BAD_STATES[name])
    with pytest.raises(st.RerunRefused):
        st.check_rerun_allowed(tmp_path)


def test_a_state_under_a_named_run_must_carry_that_run_id(tmp_path):
    from avocado_flash_remote.cmd_status import _load_run

    _mutate(tmp_path, _set("run_id", "run-2"))
    assert _load_run(tmp_path, "run-1").status == "unparseable"


def test_a_well_formed_armed_state_still_parses(tmp_path):
    s = _walk_to_verified(_new(tmp_path))
    s = st.transition(s, "arming", armed={"entry_number": "", "label": "x", "preexisting_boot_order": "0001",
                                          "preexisting_next": "", "next_armed": False})
    s = st.transition(s, "armed", armed={"entry_number": "0005", "label": "x", "preexisting_boot_order": "0001",
                                         "preexisting_next": "", "next_armed": True})
    assert st.load_state(tmp_path).status == "ok"


def test_load_run_refuses_a_symlinked_run_directory_or_state_file(tmp_path):
    from avocado_flash_remote.cmd_status import _load_run

    _new(tmp_path)
    real = tmp_path / "run-1"
    link = tmp_path / "run-9"
    link.symlink_to(real)
    assert _load_run(tmp_path, "run-9").status == "unparseable"
    other = tmp_path / "other.json"
    other.write_text((real / "state.json").read_text())
    (real / "state.json").unlink()
    (real / "state.json").symlink_to(other)
    assert _load_run(tmp_path, "run-1").status == "unparseable"


@pytest.mark.parametrize("bad", ["a b", "-x", "a\nb", "..", "a/b"])
def test_load_run_refuses_a_malformed_run_id(tmp_path, bad):
    from avocado_flash_remote.cmd_status import _load_run

    assert _load_run(tmp_path, bad).status == "unparseable"


def test_no_recovery_text_claims_restore_removes_a_boot_entry():
    """Restore only clears BootNext and removes staging; the boot entry is the firmware's own."""
    for action, text in st._RECOVERY_TEXT.items():
        low = text.lower()
        for stale in ("removes any boot entry", "remove the boot entry", "removes the entry", "entry this run created"):
            assert stale not in low, (action, stale)
    for action in ("restore-unknown-arm", "restore", "restore-then-restart"):
        assert "deletes no boot entry" in st._RECOVERY_TEXT[action].lower(), action
