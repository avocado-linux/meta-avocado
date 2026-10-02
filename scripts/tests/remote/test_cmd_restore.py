"""Tests for the restore subcommand: disarm and cleanup only, never a rollback."""

import os
from types import SimpleNamespace as NS

import pytest

from avocado_flash_remote import state as st
from avocado_flash_remote.arm import ArmRecord
from avocado_flash_remote.cmd_restore import (
    NOTE_LINE,
    StagingRefused,
    check_staging_path,
    run_restore,
)
from avocado_flash_remote.ops import RecordingOps

LABEL = "avocado-emmc-oneshot"
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


NEW = f"Boot0005* {LABEL}\tHD(11,GPT,1,0x0,0x0)/File(\\EFI\\BOOT\\BOOTAA64.EFI)"


def make_profile(staging):
    return NS(
        arm=NS(strategy="uefi-bootnext", params={"label": LABEL}),
        staging=NS(dir=str(staging)),
    )


@pytest.fixture
def env(tmp_path):
    staging = tmp_path / "var" / "lib" / "staging"
    staging.mkdir(parents=True)
    (staging / "boot.img").write_bytes(b"x")
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


def assert_safe(ops, allowed_b=("0005",)):
    for ln in ops.log:
        parts = ln.split()
        if parts and parts[0] == "efibootmgr":
            assert "-o" not in parts and "-O" not in parts and "-c" not in parts, ln
            assert "-C" not in parts, ln
            if "-B" in parts:
                assert parts[parts.index("-b") + 1] in allowed_b, ln


def test_restore_after_armed_matches_golden_sequence(env):
    mk_state(env, "armed", rec())
    ops = RecordingOps(
        {LIST: [efi(nxt="0005", extra=[NEW]), efi(nxt="0005", extra=[NEW]), efi()]}
    )
    r, removed, out = go(env, ops)
    assert r.exit_code == 0
    assert mutations(ops) == ["efibootmgr -N", "efibootmgr -B -b 0005"]
    assert removed == [str(env.staging)]
    assert NOTE_LINE in out
    assert_safe(ops)


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


def test_emergency_disarm_removes_only_labelled_entries(env):
    (env.state_dir / "current").write_text("r1\n")
    extra = [NEW, "Boot0007* avocado-emmc-oneshot-old\tx", "Boot0009* UEFI Shell"]
    ops = RecordingOps({LIST: efi(nxt="0005", extra=extra)})
    r, removed, out = go(env, ops, emergency_disarm=True, ack_run_id="yes")
    assert r.exit_code == 0
    assert mutations(ops) == ["efibootmgr -N", "efibootmgr -B -b 0005"]
    assert removed == []
    assert NOTE_LINE in out
    assert_safe(ops)


def test_emergency_leaves_foreign_bootnext(env):
    (env.state_dir / "current").write_text("r1\n")
    ops = RecordingOps({LIST: efi(nxt="0002", extra=[NEW])})
    r, _, _ = go(env, ops, emergency_disarm=True, ack_run_id="yes")
    assert r.exit_code == 0
    assert mutations(ops) == ["efibootmgr -B -b 0005"]
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
            LIST: [efi(extra=[NEW]), efi(extra=[NEW])],
            "efibootmgr -B -b 0005": OpFailed(["efibootmgr", "-B", "-b", "0005"], 1, "no"),
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
    assert mutations(ops) == ["efibootmgr -N", "efibootmgr -B -b 0005"]
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


def test_label_disarm_deletes_a_labelled_entry_that_is_not_in_boot_order(env):
    arming_state(env)
    live = efi(nxt="0005", extra=[NEW])
    ops = RecordingOps({LIST: [live, efi()]})
    r, removed, out = go(env, ops)
    assert r.exit_code == 0, out
    assert mutations(ops) == ["efibootmgr -N", "efibootmgr -B -b 0005"]


def test_label_disarm_refuses_an_entry_that_is_in_boot_order(env):
    arming_state(env)
    ops = RecordingOps({LIST: [efi(order="0001,0005,0002", extra=[NEW]), efi(order="0001,0005,0002", extra=[NEW])]})
    r, removed, out = go(env, ops)
    text = "\n".join(out)
    assert r.exit_code == 1
    assert mutations(ops) == []
    assert removed == []
    assert "0005" in text and "BootOrder" in text
    assert "efibootmgr -v" in text  # the operator is told where to look
    assert st.load_state(env.state_dir).state.phase == "arming"


def test_label_disarm_refuses_the_entry_the_board_booted_from(env):
    arming_state(env)
    ops = RecordingOps({LIST: [efi(current="0005", extra=[NEW]), efi(current="0005", extra=[NEW])]})
    r, removed, out = go(env, ops)
    assert r.exit_code == 1
    assert mutations(ops) == []
    assert removed == []
    assert "0005" in "\n".join(out) and "BootCurrent" in "\n".join(out)
    assert st.load_state(env.state_dir).state.phase == "arming"


def test_label_disarm_refuses_everything_when_any_labelled_entry_is_bootable(env):
    arming_state(env)
    two = [NEW, f"Boot0006* {LABEL}\tHD(1,GPT,2,0x0,0x0)/File(\\EFI\\BOOT\\BOOTAA64.EFI)"]
    live = efi(order="0001,0006,0002", nxt="0005", extra=two)
    ops = RecordingOps({LIST: [live, live]})
    r, _, out = go(env, ops)
    assert r.exit_code == 1
    assert mutations(ops) == []  # not even the safe sibling or BootNext: ambiguity refuses


def test_emergency_disarm_also_refuses_a_labelled_entry_in_boot_order(env):
    (env.state_dir / "current").write_text("r1\n")
    ops = RecordingOps({LIST: efi(order="0001,0005,0002", extra=[NEW])})
    r, _, out = go(env, ops, emergency_disarm=True, ack_run_id="yes")
    assert r.exit_code == 1
    assert mutations(ops) == []
    assert "0005" in "\n".join(out) and "BootOrder" in "\n".join(out)


def test_emergency_disarm_also_refuses_the_booted_entry(env):
    (env.state_dir / "current").write_text("r1\n")
    ops = RecordingOps({LIST: efi(current="0005", extra=[NEW])})
    r, _, out = go(env, ops, emergency_disarm=True, ack_run_id="yes")
    assert r.exit_code == 1
    assert mutations(ops) == []


def test_emergency_disarm_on_a_held_lock_is_bounded_and_prints_the_holder_and_manual_steps(env):
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
    assert "efibootmgr -v" in text and "efibootmgr -N" in text and "efibootmgr -B -b" in text
    assert LABEL in text


def test_held_lock_text_first_says_to_stop_when_the_holder_is_alive_and_never_calls_it_hung(env):
    ops = RecordingOps({LIST: [efi(extra=[NEW])]})
    with OnBoardLock(env.state_dir / cmd_write.LOCK_NAME, run_id="long-writer"):
        r, _removed, out = go(env, ops, emergency_disarm=True, ack_run_id="because", lock_wait=0.1)
    lines = [ln for ln in out]
    text = "\n".join(lines)
    assert "hung" not in text.lower()
    stop = next(i for i, ln in enumerate(lines) if "STOP" in ln)
    first_manual = next(i for i, ln in enumerate(lines) if "efibootmgr" in ln)
    assert stop < first_manual, "the stop condition must come before any manual command"
    stop_line = lines[stop]
    assert "alive" in stop_line and "phase" in stop_line and "moving" in stop_line
    assert "healthy" in text and "status" in text


def test_held_lock_manual_steps_clear_bootnext_only_when_it_points_at_the_labelled_entry(env):
    ops = RecordingOps({LIST: [efi(extra=[NEW])]})
    with OnBoardLock(env.state_dir / cmd_write.LOCK_NAME, run_id="w"):
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
    ops = RecordingOps({LIST: efi(nxt="0005", extra=[NEW])})
    lock = OnBoardLock(env.state_dir / cmd_write.LOCK_NAME, run_id="slow-writer")
    lock.__enter__()
    threading.Timer(0.2, lambda: lock.__exit__(None, None, None)).start()
    t0 = time.monotonic()
    r, _, out = go(env, ops, emergency_disarm=True, ack_run_id="yes", lock_wait=5)
    assert r.exit_code == 0, out
    assert time.monotonic() - t0 < 4
    assert mutations(ops) == ["efibootmgr -N", "efibootmgr -B -b 0005"]


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
    ops = RecordingOps({LIST: efi(nxt="0005", extra=extra)})
    r, _removed, _out = go(env, ops, emergency_disarm=True, ack_run_id="yes")
    assert r.exit_code == 0
    assert mutations(ops) == ["efibootmgr -N", "efibootmgr -B -b 0005"]
    assert_safe(ops)
