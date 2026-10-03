"""Tests for the restore subcommand: disarm and cleanup only, never a rollback."""

import json
import os
from types import SimpleNamespace as NS

import pytest

from avocado_flash_remote import cmd_restore
from avocado_flash_remote import state as st
from avocado_flash_remote.arm import ArmRecord
from avocado_flash_remote.cmd_restore import (
    NOTE_LINE,
    StagingRefused,
    check_staging_path,
    run_restore,
)
from avocado_flash_remote.profile import STAGING_MARKER
from avocado_flash_remote.ops import RecordingOps

LABEL = "UEFI eMMC Device"
LIST = "efibootmgr -v"
ORDER = "0001,0002,0003"


def efi(order=ORDER, nxt=None, current="0001", extra=()):
    lines = []
    if nxt:
        lines.append(f"BootNext: {nxt}")
    lines += [f"BootCurrent: {current}", "Timeout: 5 seconds", f"BootOrder: {order}"]
    lines += ["Boot0001* UEFI NVMe", "Boot0002* UEFI eMMC"]
    lines += list(extra)
    return "\n".join(lines) + "\n"


# The firmware's own storage entry (a full device path); the tool arms it and never creates it.
NEW = f"Boot0005* {LABEL}\tVenHw(1e5a432c-0000-0000-0000-000000000000)/SD(0)"


def make_profile(staging):
    return NS(
        arm=NS(strategy="uefi-bootnext", params={"entry_label": LABEL}),
        staging=NS(dir=str(staging)),
    )


@pytest.fixture
def env(tmp_path):
    staging = tmp_path / "var" / "lib" / "staging"
    staging.mkdir(parents=True)
    (staging / "boot.img").write_bytes(b"x")
    (staging / STAGING_MARKER).write_text("staged\n")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    return NS(staging=staging, state_dir=state_dir, profile=make_profile(staging))


def mk_state(env, phase, armed=None):
    s = st.create_run(
        env.state_dir,
        run_id="r1",
        profile_hash="p",
        plan_hash="q",
        board_identity={},
        image_roles=[],
        arm=True,
    )
    if phase == "planned":
        return s
    s = st.transition(s, "table-writing")
    if phase == "table-writing":
        return s
    s = st.transition(s, "table-written")
    s = st.transition(s, "verified")
    if phase == "verified":
        return s
    if phase in ("armed", "complete"):
        s = st.transition(s, "armed", armed=armed)
        if phase == "complete":
            s = st.transition(s, "complete")
        return s
    return st.transition(s, "failed", error="boom")


def rec(**kw):
    base = dict(
        entry_number="0005", label=LABEL, preexisting_boot_order=ORDER,
        preexisting_next="", next_armed=True,
    )  # fmt: skip
    base.update(kw)
    return ArmRecord(**base).to_dict()


def go(env, ops, **kw):
    # A non-terminal run needs its acknowledgement; supply it unless the test
    # is about the emergency path or sets ack_run_id itself.
    if not kw.get("emergency_disarm"):
        kw.setdefault("ack_run_id", "r1")
    removed = []

    def rm(path):
        removed.append(path)

    kw.setdefault("remove_tree", rm)
    out = []
    r = run_restore(
        ops, env.profile, state_dir=env.state_dir, staging_dir=str(env.staging),
        out=out.append, **kw,
    )  # fmt: skip
    return r, removed, out


def mutations(ops):
    return [
        ln for ln in ops.log
        if ln.startswith("efibootmgr") and ln != LIST and ln != "efibootmgr --help"
    ]  # fmt: skip


def assert_safe(ops):
    for ln in ops.log:
        parts = ln.split()
        if parts and parts[0] == "efibootmgr":
            for opt in ("-C", "-B", "-b", "-o", "-O", "-c"):
                assert opt not in parts, ln


def test_restore_after_armed_clears_bootnext_and_deletes_no_entry(env):
    mk_state(env, "armed", rec())
    ops = RecordingOps(
        {LIST: [efi(nxt="0005", extra=[NEW]), efi(nxt="0005", extra=[NEW]), efi()]}
    )
    r, removed, out = go(env, ops)
    assert r.exit_code == 0
    # Deliberate change from the kit sequence (-N then -B -b 0005): the entry is the firmware's own.
    assert mutations(ops) == ["efibootmgr -N"]
    assert removed == [str(env.staging)]
    assert NOTE_LINE in out
    assert_safe(ops)


def test_restore_after_the_boot_consumed_bootnext_is_a_note_and_exit_zero(env):
    mk_state(env, "armed", rec())
    ops = RecordingOps({LIST: [efi(extra=[NEW]), efi(extra=[NEW]), efi(extra=[NEW])]})
    r, removed, out = go(env, ops)
    assert r.exit_code == 0
    assert mutations(ops) == []
    assert removed == [str(env.staging)]
    assert any("already consumed" in ln for ln in out)


def test_restore_reports_boot_order_verified(env):
    mk_state(env, "armed", rec())
    ops = RecordingOps({LIST: [efi(extra=[NEW]), efi(extra=[NEW]), efi()]})
    r, _, out = go(env, ops)
    assert any("BootOrder" in ln and ORDER in ln for ln in out)
    assert r.exit_code == 0


def test_boot_order_mismatch_after_disarm_fails_and_keeps_staging(env):
    mk_state(env, "armed", rec())
    ops = RecordingOps({LIST: [efi(extra=[NEW]), efi(extra=[NEW]), efi(order="0005,0001")]})
    r, removed, out = go(env, ops)
    assert r.exit_code == 1
    assert removed == []


def test_failed_before_arm_makes_no_efibootmgr_calls(env):
    mk_state(env, "failed")
    ops = RecordingOps()
    r, removed, out = go(env, ops)
    assert r.exit_code == 0
    assert ops.log == []
    assert removed == [str(env.staging)]
    assert NOTE_LINE in out


def test_table_writing_state_prints_note_and_only_cleans_staging(env):
    mk_state(env, "table-writing")
    ops = RecordingOps()
    r, removed, out = go(env, ops)
    assert r.exit_code == 0
    assert ops.log == []
    assert removed == [str(env.staging)]
    assert NOTE_LINE in out


def test_planned_state_has_no_note(env):
    mk_state(env, "planned")
    ops = RecordingOps()
    r, removed, out = go(env, ops)
    assert r.exit_code == 0
    assert NOTE_LINE not in out


def test_after_reboot_leaves_entries_alone_and_cleans_staging(env):
    mk_state(env, "armed", rec())
    ops = RecordingOps({LIST: efi(current="0005", extra=[NEW])})
    r, removed, out = go(env, ops)
    assert r.exit_code == 0
    assert mutations(ops) == []
    assert removed == [str(env.staging)]
    assert any("0005" in ln and "booted" in ln for ln in out)
    assert NOTE_LINE in out


def test_label_mismatch_leaves_entry_alone_and_reports(env):
    mk_state(env, "armed", rec())
    other = "Boot0005* someone-elses-entry\tHD(1,GPT)/File(x)"
    ops = RecordingOps({LIST: [efi(extra=[other]), efi(extra=[other]), efi(extra=[other])]})
    r, removed, out = go(env, ops)
    assert r.exit_code == 1
    assert not any("-B" in ln.split() for ln in ops.log)
    assert removed == []
    assert any("0005" in ln and LABEL in ln for ln in out)


def test_unparseable_state_refuses_without_mutation(env):
    (env.state_dir / "current").write_text("r1\n")
    (env.state_dir / "r1").mkdir()
    (env.state_dir / "r1" / "state.json").write_text("{not json")
    ops = RecordingOps()
    r, removed, out = go(env, ops)
    assert r.exit_code == 1
    assert ops.log == []
    assert removed == []
    assert any("--emergency-disarm" in ln for ln in out)
    assert NOTE_LINE in out


def test_emergency_requires_acknowledgement(env):
    (env.state_dir / "current").write_text("r1\n")
    ops = RecordingOps()
    r, removed, out = go(env, ops, emergency_disarm=True)
    assert r.exit_code == 1
    assert ops.log == []
    assert removed == []


def test_emergency_disarm_clears_bootnext_for_the_labelled_entry_and_deletes_nothing(env):
    (env.state_dir / "current").write_text("r1\n")
    extra = [NEW, "Boot0007* avocado-emmc-oneshot-old\tx", "Boot0009* UEFI Shell"]
    ops = RecordingOps({LIST: [efi(nxt="0005", extra=extra), efi(extra=extra)]})
    r, removed, out = go(env, ops, emergency_disarm=True, ack_run_id="yes")
    assert r.exit_code == 0
    assert mutations(ops) == ["efibootmgr -N"]
    assert removed == []
    assert NOTE_LINE in out
    assert_safe(ops)


def test_emergency_leaves_foreign_bootnext(env):
    (env.state_dir / "current").write_text("r1\n")
    ops = RecordingOps({LIST: efi(nxt="0002", extra=[NEW])})
    r, _, _ = go(env, ops, emergency_disarm=True, ack_run_id="yes")
    assert r.exit_code == 0
    assert mutations(ops) == []
    assert_safe(ops)


def test_absent_state_cleans_staging_and_exits_zero(env):
    ops = RecordingOps()
    r, removed, out = go(env, ops)
    assert r.exit_code == 0
    assert ops.log == []
    assert removed == [str(env.staging)]
    assert NOTE_LINE in out


def test_idempotent_second_run_finds_nothing(env):
    mk_state(env, "armed", rec())
    ops = RecordingOps({LIST: [efi(extra=[NEW]), efi(extra=[NEW]), efi()]})
    r1, _, _ = go(env, ops)
    assert r1.exit_code == 0
    shutil_target = env.staging
    for p in shutil_target.iterdir():
        p.unlink()
    shutil_target.rmdir()
    ops2 = RecordingOps({LIST: [efi(), efi(), efi()]})
    r2, removed2, _ = go(env, ops2)
    assert r2.exit_code == 0
    assert mutations(ops2) == []
    assert removed2 == []


def test_default_remove_tree_deletes_staging(env):
    mk_state(env, "failed")
    out = []
    r = run_restore(
        RecordingOps(), env.profile, state_dir=env.state_dir,
        staging_dir=str(env.staging), out=out.append,
    )  # fmt: skip
    assert r.exit_code == 0
    assert not env.staging.exists()


def test_restore_leaves_a_staging_directory_the_stage_step_never_marked(env):
    (env.staging / STAGING_MARKER).unlink()
    mk_state(env, "failed")
    out = []
    r = run_restore(
        RecordingOps(), env.profile, state_dir=env.state_dir,
        staging_dir=str(env.staging), out=out.append,
    )  # fmt: skip
    assert r.exit_code == 1
    assert (env.staging / "boot.img").exists(), "an unmarked directory is not ours to remove"
    assert any("staging NOT removed" in ln and STAGING_MARKER in ln for ln in out), out


def test_restore_without_state_also_leaves_an_unmarked_staging_directory(env):
    (env.staging / STAGING_MARKER).unlink()
    out = []
    r = run_restore(
        RecordingOps(), env.profile, state_dir=env.state_dir,
        staging_dir=str(env.staging), out=out.append,
    )  # fmt: skip
    assert r.exit_code == 1 and env.staging.exists()


def test_a_marker_that_is_a_symlink_does_not_authorise_removal(env, tmp_path):
    (env.staging / STAGING_MARKER).unlink()
    target = tmp_path / "elsewhere"
    target.write_text("x")
    os.symlink(target, env.staging / STAGING_MARKER)
    with pytest.raises(StagingRefused, match="marker"):
        check_staging_path(str(env.staging), str(env.staging))


def test_staging_guard_rejects_wrong_path(env, tmp_path):
    other = tmp_path / "a" / "b" / "other"
    other.mkdir(parents=True)
    with pytest.raises(StagingRefused):
        check_staging_path(str(other), str(env.staging))


def test_staging_guard_rejects_symlink(tmp_path):
    real = tmp_path / "a" / "b" / "real"
    real.mkdir(parents=True)
    link = tmp_path / "a" / "b" / "link"
    os.symlink(real, link)
    with pytest.raises(StagingRefused):
        check_staging_path(str(link), str(link))


def test_staging_guard_rejects_a_path_reached_through_a_symlinked_parent(tmp_path):
    real = tmp_path / "a" / "b" / "real"
    (real / "stage").mkdir(parents=True)
    (real / "stage" / STAGING_MARKER).write_text("x")
    link = tmp_path / "a" / "b" / "link"
    os.symlink(real, link)
    through = str(link / "stage")
    with pytest.raises(StagingRefused, match="symlink"):
        check_staging_path(through, through)


def test_staging_guard_rejects_a_mountpoint(env, monkeypatch):
    monkeypatch.setattr(cmd_restore, "_ismount", lambda p: str(p) == str(env.staging))
    with pytest.raises(StagingRefused, match="mount"):
        check_staging_path(str(env.staging), str(env.staging))


@pytest.mark.parametrize("kind", ["dir", "file"])
def test_staging_guard_rejects_an_entry_on_another_device(env, monkeypatch, kind):
    other = env.staging / "inner"
    if kind == "dir":
        other.mkdir()
        (other / "f").write_text("x")
    else:
        other.write_text("x")
    real_dev = cmd_restore._device_of
    monkeypatch.setattr(cmd_restore, "_device_of", lambda p: -1 if str(p) == str(other) else real_dev(p))
    with pytest.raises(StagingRefused, match="device"):
        check_staging_path(str(env.staging), str(env.staging))


def test_restore_removes_nothing_when_an_entry_sits_on_another_device(env, monkeypatch):
    mk_state(env, "failed")
    other = env.staging / "inner"
    other.mkdir()
    real_dev = cmd_restore._device_of
    monkeypatch.setattr(cmd_restore, "_device_of", lambda p: -1 if str(p) == str(other) else real_dev(p))
    out = []
    r = run_restore(
        RecordingOps(), env.profile, state_dir=env.state_dir,
        staging_dir=str(env.staging), out=out.append,
    )  # fmt: skip
    assert r.exit_code == 1 and (env.staging / "boot.img").exists() and other.exists()
    assert any("staging NOT removed" in ln and "device" in ln for ln in out), out


@pytest.mark.parametrize("bad", ["/", "/run", ""])
def test_staging_guard_rejects_shallow_paths(bad):
    with pytest.raises(StagingRefused):
        check_staging_path(bad, bad)


def test_staging_mismatch_in_run_restore_refuses(env, tmp_path):
    mk_state(env, "failed")
    removed = []
    out = []
    r = run_restore(
        RecordingOps(), env.profile, state_dir=env.state_dir,
        staging_dir=str(tmp_path), remove_tree=removed.append, out=out.append,
    )  # fmt: skip
    assert r.exit_code == 1
    assert removed == []


def test_disarm_failure_keeps_staging(env):
    mk_state(env, "armed", rec())
    from avocado_flash_remote.ops import OpFailed

    ops = RecordingOps(
        {
            LIST: [efi(nxt="0005", extra=[NEW]), efi(nxt="0005", extra=[NEW])],
            "efibootmgr -N": OpFailed(["efibootmgr", "-N"], 1, "no"),
        }
    )
    r, removed, out = go(env, ops)
    assert r.exit_code == 1
    assert removed == []


# ---- 5.15: lock, acknowledgement, terminal state, true recovery text --------

import re

from avocado_flash_remote import cmd_write
from avocado_flash_remote.state import LockHeld, OnBoardLock


def go_raw(env, ops, **kw):
    """Like go() but with no implicit acknowledgement."""
    removed = []
    out = []
    r = run_restore(
        ops, env.profile, state_dir=env.state_dir, staging_dir=str(env.staging),
        out=out.append, remove_tree=removed.append, **kw,
    )  # fmt: skip
    return r, removed, out


def image_writing_state(env):
    s = st.create_run(
        env.state_dir, run_id="r1", profile_hash="p", plan_hash="q",
        board_identity={}, image_roles=["boot"], arm=True,
    )  # fmt: skip
    s = st.transition(s, "table-writing")
    s = st.transition(s, "table-written")
    return st.transition(s, "image-writing", image="boot")


def test_restore_while_another_holder_has_the_lock_refuses_and_deletes_nothing(env):
    image_writing_state(env)
    ops = RecordingOps()
    with OnBoardLock(env.state_dir / cmd_write.LOCK_NAME, run_id="writer"):
        r, removed, out = go(env, ops)
    assert r.exit_code == 1
    assert removed == []
    assert ops.log == []
    assert env.staging.exists()
    assert "lock" in "\n".join(out)
    assert st.load_state(env.state_dir).state.phase == "image-writing"


def test_emergency_disarm_also_needs_the_lock(env):
    ops = RecordingOps({LIST: [efi(extra=[NEW])]})
    with OnBoardLock(env.state_dir / cmd_write.LOCK_NAME, run_id="writer"):
        r, _, out = go(env, ops, emergency_disarm=True, ack_run_id="because", lock_wait=0.1)
    assert r.exit_code == 1
    assert mutations(ops) == []


def test_restore_releases_the_lock_when_done(env):
    mk_state(env, "failed")
    go(env, RecordingOps())
    with OnBoardLock(env.state_dir / cmd_write.LOCK_NAME):
        pass


@pytest.mark.parametrize("phase", ["planned", "table-writing", "verified", "armed"])
def test_non_terminal_run_without_ack_refuses_and_touches_nothing(env, phase):
    mk_state(env, phase, rec() if phase == "armed" else None)
    ops = RecordingOps()
    r, removed, out = go_raw(env, ops)
    assert r.exit_code == 1
    assert ops.log == []
    assert removed == []
    assert "--ack-run r1" in "\n".join(out)
    assert st.load_state(env.state_dir).state.phase == phase


def test_image_writing_without_ack_refuses(env):
    image_writing_state(env)
    ops = RecordingOps()
    r, removed, out = go_raw(env, ops)
    assert r.exit_code == 1 and removed == [] and ops.log == []


def test_wrong_ack_refuses(env):
    image_writing_state(env)
    r, removed, _ = go_raw(env, RecordingOps(), ack_run_id="some-other-run")
    assert r.exit_code == 1 and removed == []


def test_acknowledged_restore_disarms_cleans_and_unblocks_the_next_run(env):
    mk_state(env, "armed", rec())
    ops = RecordingOps({LIST: [efi(nxt="0005", extra=[NEW]), efi(nxt="0005", extra=[NEW]), efi()]})
    r, removed, out = go_raw(env, ops, ack_run_id="r1")
    assert r.exit_code == 0
    assert mutations(ops) == ["efibootmgr -N"]
    assert removed == [str(env.staging)]
    loaded = st.load_state(env.state_dir)
    assert loaded.state.phase == "restored"
    assert loaded.state.phase in st.TERMINAL
    # a following plan and write are accepted
    assert st.check_rerun_allowed(env.state_dir).recovery_only is False
    cmd_write._prior_state_gate(env.state_dir, "r2", None)


def test_restored_run_cannot_be_replayed_as_the_same_plan(env):
    image_writing_state(env)
    go_raw(env, RecordingOps(), ack_run_id="r1")
    with pytest.raises(cmd_write._Refusal):
        cmd_write._prior_state_gate(env.state_dir, "r1", None)


def test_failed_restore_does_not_advance_the_state(env):
    mk_state(env, "armed", rec())
    ops = RecordingOps({LIST: [efi(nxt="0005", extra=[NEW]), efi(nxt="0005", extra=[NEW]), efi(order="0002,0001")]})
    r, removed, _ = go_raw(env, ops, ack_run_id="r1")
    assert r.exit_code == 1
    assert st.load_state(env.state_dir).state.phase == "armed"


def test_failed_run_restore_needs_no_ack_and_ends_restored(env):
    mk_state(env, "failed")
    r, removed, _ = go_raw(env, RecordingOps())
    assert r.exit_code == 0
    assert st.load_state(env.state_dir).state.phase == "restored"


def test_emergency_hint_names_the_real_flag(env):
    (env.state_dir / "current").write_text("r1\n")
    r, _, out = go_raw(env, RecordingOps())
    text = "\n".join(out)
    assert r.exit_code == 1
    assert "--ack-run" in text
    assert not re.search(r"--ack(?!-run)", text)


# ---- 5.20: label-based disarm never deletes a bootable entry; emergency lock wait ----


def arming_state(env):
    s = mk_state(env, "verified")
    return st.transition(s, "arming", armed=rec(entry_number="", next_armed=False))


def test_label_disarm_clears_bootnext_of_the_single_labelled_entry_and_deletes_nothing(env):
    arming_state(env)
    live = efi(nxt="0005", extra=[NEW])
    ops = RecordingOps({LIST: [live, efi(extra=[NEW])]})
    r, removed, out = go(env, ops)
    assert r.exit_code == 0, out
    assert mutations(ops) == ["efibootmgr -N"]
    assert_safe(ops)


def test_label_disarm_proceeds_for_an_entry_that_is_in_boot_order(env):
    # Deliberate change: the firmware's own entry normally sits in BootOrder; the old refusal guarded a
    # created entry from being deleted, and nothing is deleted now.
    s0 = mk_state(env, "verified")
    st.transition(s0, "arming", armed=rec(entry_number="", next_armed=False, preexisting_boot_order="0001,0005,0002"))
    live = efi(order="0001,0005,0002", nxt="0005", extra=[NEW])
    ops = RecordingOps({LIST: [live, efi(order="0001,0005,0002", extra=[NEW])]})
    r, removed, out = go(env, ops)
    assert r.exit_code == 0, out
    assert mutations(ops) == ["efibootmgr -N"]


def test_label_disarm_tolerates_the_entry_the_board_booted_from(env):
    arming_state(env)
    live = efi(current="0005", extra=[NEW])
    ops = RecordingOps({LIST: [live, live]})
    r, removed, out = go(env, ops)
    assert r.exit_code == 0, out
    assert mutations(ops) == []
    assert any("already consumed" in ln for ln in out)


def test_label_disarm_with_two_labelled_entries_mutates_nothing_and_keeps_staging(env):
    arming_state(env)
    two = [NEW, f"Boot0006* {LABEL}\tVenHw(1)/SD(1)"]
    live = efi(order="0001,0006,0002", nxt="0005", extra=two)
    ops = RecordingOps({LIST: [live, live]})
    r, removed, out = go(env, ops)
    assert r.exit_code == 1
    assert mutations(ops) == [] and removed == []
    assert "2 boot entries" in "\n".join(out)
    assert st.load_state(env.state_dir).state.phase == "arming"


def test_emergency_disarm_with_the_entry_in_boot_order_and_no_bootnext_changes_nothing(env):
    (env.state_dir / "current").write_text("r1\n")
    ops = RecordingOps({LIST: efi(order="0001,0005,0002", extra=[NEW])})
    r, _, out = go(env, ops, emergency_disarm=True, ack_run_id="yes")
    assert r.exit_code == 0
    assert mutations(ops) == []


def test_emergency_disarm_with_the_booted_entry_changes_nothing(env):
    (env.state_dir / "current").write_text("r1\n")
    ops = RecordingOps({LIST: efi(current="0005", extra=[NEW])})
    r, _, out = go(env, ops, emergency_disarm=True, ack_run_id="yes")
    assert r.exit_code == 0
    assert mutations(ops) == []


def _gone_pid():
    """A pid that belonged to a process which has exited and been reaped."""
    import subprocess
    import sys

    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert not os.path.exists(f"/proc/{child.pid}")
    return child.pid


class _HeldBy:
    """Holds the on-board lock, then rewrites its holder record to name ``pid`` (a live or gone process)."""

    def __init__(self, env, pid, run_id="writer"):
        self.lock = OnBoardLock(env.state_dir / cmd_write.LOCK_NAME, run_id=run_id)
        self.pid, self.run_id = pid, run_id

    def __enter__(self):
        self.lock.__enter__()
        fh = self.lock._fh
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps({"pid": self.pid, "run_id": self.run_id}))
        fh.flush()
        return self

    def __exit__(self, *exc):
        self.lock.__exit__(*exc)


def test_emergency_disarm_on_a_held_lock_is_bounded_and_prints_the_holder(env):
    import time

    ops = RecordingOps({LIST: [efi(extra=[NEW])]})
    with OnBoardLock(env.state_dir / cmd_write.LOCK_NAME, run_id="hung-writer"):
        t0 = time.monotonic()
        r, removed, out = go(env, ops, emergency_disarm=True, ack_run_id="because", lock_wait=0.3)
        elapsed = time.monotonic() - t0
    text = "\n".join(out)
    assert r.exit_code == 1
    assert 0.25 <= elapsed < 5
    assert ops.log == [] and removed == []
    assert f'"pid": {os.getpid()}' in text or f"pid {os.getpid()}" in text
    assert "hung-writer" in text


def test_the_lock_acquired_emergency_path_also_warns_to_check_for_running_tools(env):
    # An orphaned dd (own session) can outlive a SIGKILLed runner while the lock is free, so the
    # ps warning cannot live only on the lock-held path.
    ops = RecordingOps({LIST: [efi(extra=[NEW])]})
    r, _removed, out = go(env, ops, emergency_disarm=True, ack_run_id="yes")
    text = "\n".join(out)
    assert "no dd, sfdisk or efibootmgr is still running" in text
    assert "ps -ef" in text


def test_a_live_holder_gets_no_manual_steps_only_wait_and_status(env):
    # image-writing is one phase for the whole dd, and between the lock and the first state record the
    # status still shows the previous run's terminal phase: "the phase has stopped moving" proves nothing.
    ops = RecordingOps({LIST: [efi(extra=[NEW])]})
    with OnBoardLock(env.state_dir / cmd_write.LOCK_NAME, run_id="long-writer"):
        r, removed, out = go(env, ops, emergency_disarm=True, ack_run_id="because", lock_wait=0.1)
    text = "\n".join(out)
    assert r.exit_code == 1 and removed == [] and ops.log == []
    assert "efibootmgr" not in text
    assert "hung" not in text.lower() and "stopped moving" not in text
    assert "alive" in text and "wait" in text and "status" in text
    assert "no boot entry or staging was touched" in text


def test_an_unreadable_holder_record_is_treated_as_a_live_holder(env):
    ops = RecordingOps({LIST: [efi(extra=[NEW])]})
    for raw in ('{"pid": "not-a-number", "run_id": "x"}', "garbage", ""):
        with _HeldBy(env, 1) as held:
            fh = held.lock._fh
            fh.seek(0)
            fh.truncate()
            fh.write(raw)
            fh.flush()
            r, _removed, out = go(env, RecordingOps({LIST: [efi(extra=[NEW])]}), emergency_disarm=True, ack_run_id="because", lock_wait=0.1)
        text = "\n".join(out)
        assert r.exit_code == 1 and "efibootmgr" not in text, raw
        assert "wait" in text and "status" in text, raw


def test_a_gone_holder_gets_the_manual_steps_with_the_stop_check_first(env):
    ops = RecordingOps({LIST: [efi(extra=[NEW])]})
    pid = _gone_pid()
    with _HeldBy(env, pid, "dead-writer"):
        r, removed, out = go(env, ops, emergency_disarm=True, ack_run_id="because", lock_wait=0.1)
    lines = list(out)
    text = "\n".join(lines)
    assert r.exit_code == 1 and removed == [] and ops.log == []
    assert f"pid {pid}" in text and "dead-writer" in text
    assert "is gone" in text
    assert "efibootmgr -v" in text and "efibootmgr -N" in text
    assert "efibootmgr -B" not in text and "delete no boot entry" in text
    assert LABEL in text
    # The tool a dead runner started may still hold the lock: say to look before touching anything.
    check = next(i for i, ln in enumerate(lines) if "ps" in ln and "dd" in ln)
    first_manual = next(i for i, ln in enumerate(lines) if ln.startswith("  efibootmgr"))
    assert check < first_manual


def test_held_lock_manual_steps_clear_bootnext_only_when_it_points_at_the_labelled_entry(env):
    ops = RecordingOps({LIST: [efi(extra=[NEW])]})
    with _HeldBy(env, _gone_pid(), "w"):
        _r, _removed, out = go(env, ops, emergency_disarm=True, ack_run_id="because", lock_wait=0.1)
    clear = next(ln for ln in out if "efibootmgr -N" in ln)
    assert "only if BootNext" in clear and LABEL in clear
    assert "unconditional" not in clear
    # every line that runs the clear mentions its condition on the same line
    assert all("only if" in ln for ln in out if "efibootmgr -N" in ln)


def test_emergency_disarm_proceeds_when_the_lock_is_released_during_the_wait(env):
    import threading
    import time

    (env.state_dir / "current").write_text("r1\n")
    ops = RecordingOps({LIST: [efi(nxt="0005", extra=[NEW]), efi(extra=[NEW])]})
    lock = OnBoardLock(env.state_dir / cmd_write.LOCK_NAME, run_id="slow-writer")
    lock.__enter__()
    threading.Timer(0.2, lambda: lock.__exit__(None, None, None)).start()
    t0 = time.monotonic()
    r, _, out = go(env, ops, emergency_disarm=True, ack_run_id="yes", lock_wait=5)
    assert r.exit_code == 0, out
    assert time.monotonic() - t0 < 4
    assert mutations(ops) == ["efibootmgr -N"]


def test_normal_restore_still_refuses_at_once_on_a_held_lock_whatever_the_wait(env):
    import time

    image_writing_state(env)
    with OnBoardLock(env.state_dir / cmd_write.LOCK_NAME, run_id="writer"):
        t0 = time.monotonic()
        r, removed, out = go(env, RecordingOps(), lock_wait=5)
        assert time.monotonic() - t0 < 2
    assert r.exit_code == 1 and removed == []


def test_emergency_disarm_leaves_a_longer_label_with_our_label_as_its_prefix(env):
    (env.state_dir / "current").write_text("r1\n")
    extra = [NEW, f"Boot0007* {LABEL} old\tHD(1,GPT)", f"Boot0008* {LABEL}x\tHD(1,GPT)"]
    ops = RecordingOps({LIST: [efi(nxt="0005", extra=extra), efi(extra=extra)]})
    r, _removed, _out = go(env, ops, emergency_disarm=True, ack_run_id="yes")
    assert r.exit_code == 0
    assert mutations(ops) == ["efibootmgr -N"]
    assert_safe(ops)


# --- restore names a run: --run-id must not restore whichever run `current` names ---


def _two_runs(env):
    """Run r1 armed and complete, then run r2 which moved `current` to itself."""
    mk_state(env, "armed", rec())
    st.create_run(
        env.state_dir, run_id="r2", profile_hash="p", plan_hash="q", board_identity={}, image_roles=[], arm=True
    )


def test_run_id_naming_a_non_current_run_does_not_restore_current(env):
    _two_runs(env)
    ops = RecordingOps({LIST: [efi(nxt="0005", extra=[NEW]), efi(nxt="0005", extra=[NEW]), efi()]})
    r, removed, out = go(env, ops, run_id="r1", ack_run_id="r1")
    # r1 is the armed run: it is disarmed, and the closed run is r1, not the current r2
    assert mutations(ops) == ["efibootmgr -N"]
    assert st.load_state(env.state_dir).state.phase == "planned"
    assert any("run r1" in ln for ln in out)


def test_run_id_that_is_current_run_restores_it(env):
    mk_state(env, "failed")
    ops = RecordingOps({})
    r, removed, out = go(env, ops, run_id="r1")
    assert r.exit_code == 0
    assert any("restoring run r1" in ln for ln in out)


def test_run_id_of_unrecorded_run_refuses_without_touching_current_run(env):
    _two_runs(env)
    ops = RecordingOps({})
    r, removed, out = go(env, ops, run_id="r9", ack_run_id="r9")
    assert r.exit_code == 1
    assert ops.log == [] and removed == []
    assert st.load_state(env.state_dir).state.run_id == "r2"


def test_run_id_whose_record_names_another_run_refuses(env):
    mk_state(env, "armed", rec())
    path = env.state_dir / "r1" / "state.json"
    data = json.loads(path.read_text())
    data["run_id"] = "other"
    path.write_text(json.dumps(data))
    ops = RecordingOps({})
    r, removed, out = go(env, ops, run_id="r1")
    assert r.exit_code == 1
    assert mutations(ops) == [] and removed == []


def test_no_run_id_names_the_run_being_restored(env):
    mk_state(env, "failed")
    r, removed, out = go(env, RecordingOps({}))
    assert any("restoring run r1 (the current run)" in ln for ln in out)


def test_bad_run_id_refuses(env):
    mk_state(env, "failed")
    ops = RecordingOps({})
    r, removed, out = go(env, ops, run_id="../x")
    assert r.exit_code == 1 and removed == [] and mutations(ops) == []


def test_restore_by_recorded_number_proceeds_for_an_entry_in_boot_order(env):
    # Deliberate change: the arm entry is the firmware's own and is normally in BootOrder.
    mk_state(env, "armed", rec(preexisting_boot_order="0001,0005,0002"))
    live = efi(order="0001,0005,0002", nxt="0005", extra=[NEW])
    after = efi(order="0001,0005,0002", extra=[NEW])
    ops = RecordingOps({LIST: [live, live, after]})
    r, removed, out = go(env, ops)
    assert r.exit_code == 0
    assert mutations(ops) == ["efibootmgr -N"]
    assert removed == [str(env.staging)]


# ---- 5.39 (2): restore reads BootNext back after clearing it ----


def test_restore_fails_when_bootnext_still_names_the_entry_after_clearing(env):
    mk_state(env, "armed", rec())
    still = efi(nxt="0005", extra=[NEW])
    ops = RecordingOps({LIST: [still, still, still]})
    r, removed, out = go_raw(env, ops, ack_run_id="r1")
    text = "\n".join(out)
    assert r.exit_code == 1
    assert mutations(ops) == ["efibootmgr -N"]
    assert "BootNext 0005 still set: DO NOT REBOOT" in text
    assert removed == []
    assert st.load_state(env.state_dir).state.phase == "armed"


def test_restore_names_the_manual_next_step_when_bootnext_stays_because_the_label_changed(env):
    mk_state(env, "armed", rec())
    renamed = efi(nxt="0005", extra=["Boot0005* Renamed by firmware\tVenHw(1e5a432c-0000-0000-0000-000000000000)/SD(0)"])
    ops = RecordingOps({LIST: [renamed, renamed, renamed]})
    r, removed, out = go_raw(env, ops, ack_run_id="r1")
    text = "\n".join(out)
    assert r.exit_code == 1 and removed == []
    assert mutations(ops) == []
    assert "BootNext 0005 still set: DO NOT REBOOT" in text
    assert "efibootmgr -N" in text and "efibootmgr -v" in text, text
    assert "delete no boot entry" in text


def test_emergency_disarm_fails_when_bootnext_still_names_the_entry_after_clearing(env):
    (env.state_dir / "current").write_text("r1\n")
    still = efi(nxt="0005", extra=[NEW])
    ops = RecordingOps({LIST: [still, still]})
    r, _, out = go(env, ops, emergency_disarm=True, ack_run_id="yes")
    assert r.exit_code == 1
    assert "BootNext 0005 still set: DO NOT REBOOT" in "\n".join(out)
