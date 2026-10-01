"""Durable state machine and lock tests (task 3.3)."""

from __future__ import annotations

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


def _walk_to_verified(s):
    s = st.transition(s, "table-written")
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


@pytest.mark.parametrize("target", ["image-writing", "verified", "armed", "complete", "planned"])
def test_no_skipping_from_planned(tmp_path, target):
    s = _new(tmp_path)
    with pytest.raises(st.IllegalTransition):
        st.transition(s, target, image="boot")


def test_no_going_back(tmp_path):
    s = st.transition(_new(tmp_path), "table-written")
    with pytest.raises(st.IllegalTransition):
        st.transition(s, "planned")


def test_images_in_profile_order_and_all_required(tmp_path):
    s = st.transition(_new(tmp_path), "table-written")
    with pytest.raises(st.IllegalTransition):
        st.transition(s, "image-writing", image="rootfs")
    with pytest.raises(st.IllegalTransition):
        st.transition(s, "verified")
    s = st.transition(s, "image-writing", image="boot")
    with pytest.raises(st.IllegalTransition):
        st.transition(s, "image-written", image="rootfs")


def test_terminal_states_are_final_and_failed_from_anywhere(tmp_path):
    s = st.transition(_new(tmp_path), "table-written")
    s = st.transition(s, "failed", error="boom")
    assert _read(tmp_path).data["error"] == "boom"
    with pytest.raises(st.IllegalTransition):
        st.transition(s, "complete")
    with pytest.raises(st.IllegalTransition):
        st.transition(s, "failed")


def test_failed_from_planned(tmp_path):
    assert st.transition(_new(tmp_path), "failed", error="x").phase == "failed"


# ---- crash injection --------------------------------------------------

POINTS = ["before-write", "after-temp-write", "after-fsync", "after-rename"]


class Boom(BaseException):
    pass


def _transitions(s):
    """Yield (name, callable) for every transition of the arm path."""
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
    assert st.RECOVERY["planned"] == "none-needed"


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
