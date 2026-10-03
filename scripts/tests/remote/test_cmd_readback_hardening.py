"""Readback copies out of an untrusted mounted image with no-follow semantics and fails closed (task 5.33)."""

from __future__ import annotations

import errno
import os
import stat

import pytest

from avocado_flash_remote import state as statemod

from test_cmd_readback_status import DISK, PART, dirs, profile, run, script  # noqa: F401
from avocado_flash_remote.cmd_readback import (
    ReadbackError,
    _default_logs,
    make_guarded_copier,
    run_readback,
)
from avocado_flash_remote.ops import OpFailed, OpResult, RecordingOps


@pytest.fixture
def tree(tmp_path):
    mnt = tmp_path / "mnt"
    out = tmp_path / "out"
    outside = tmp_path / "outside"
    for d in (mnt / "log" / "journal" / "sub", out, outside):
        d.mkdir(parents=True)
    (outside / "secret").write_text("secret")
    (mnt / "log" / "journal" / "a.journal").write_text("a")
    (mnt / "log" / "journal" / "sub" / "b.journal").write_text("b")
    (mnt / "log" / "journal" / "link").symlink_to(outside / "secret")
    (mnt / "log" / "journal" / "dirlink").symlink_to(outside)
    (mnt / "log" / "boot.log").write_text("log")
    (mnt / "log" / "evil.log").symlink_to(outside / "secret")
    return mnt, out, outside


def test_copier_never_follows_symlinks_in_a_journal_tree(tree):
    mnt, out, outside = tree
    notes = []
    copy = make_guarded_copier(str(out), str(mnt), notes.append)
    copy(str(mnt / "log" / "journal"), str(out / "journal"))
    assert (out / "journal" / "a.journal").read_text() == "a"
    assert (out / "journal" / "sub" / "b.journal").read_text() == "b"
    assert not (out / "journal" / "link").exists() and not os.path.lexists(out / "journal" / "link")
    assert not os.path.lexists(out / "journal" / "dirlink")
    assert not (out / "secret").exists()
    assert sum("symlink" in n for n in notes) == 2


def test_copier_skips_a_symlinked_file_source_and_says_so(tree):
    mnt, out, _ = tree
    notes = []
    copy = make_guarded_copier(str(out), str(mnt), notes.append)
    copy(str(mnt / "log" / "evil.log"), str(out / "evil.log"))
    assert not os.path.lexists(out / "evil.log")
    assert any("evil.log" in n and "symlink" in n for n in notes)


def test_copier_refuses_a_source_outside_the_mount(tree):
    mnt, out, outside = tree
    copy = make_guarded_copier(str(out), str(mnt), lambda n: None)
    with pytest.raises(ReadbackError, match="outside"):
        copy(str(outside / "secret"), str(out / "secret"))


def test_copier_refuses_a_source_reached_through_a_symlinked_directory(tree):
    mnt, out, outside = tree
    copy = make_guarded_copier(str(out), str(mnt), lambda n: None)
    with pytest.raises(ReadbackError, match="outside"):
        copy(str(mnt / "log" / "journal" / "dirlink" / "secret"), str(out / "s"))


def test_default_log_listing_excludes_symlinks(tree):
    mnt, _, _ = tree
    assert [os.path.basename(p) for p in _default_logs(str(mnt))] == ["boot.log"]


def test_a_journal_listing_failure_that_is_not_absence_is_not_examined(profile, dirs):
    mnt, out = dirs
    s = script(dirs)
    s[f"ls -laR {mnt}/log/journal"] = OpResult(rc=2, stderr="ls: cannot open directory: Permission denied")
    ops = RecordingOps(s)
    res, copies, lines = run(profile, dirs, ops)
    assert res.exit_code == 2
    assert any("TARGET NOT EXAMINED" in ln for ln in lines)
    assert not any("wrote no persistent journal" in ln for ln in lines)
    assert ops.log[-1] == f"umount {mnt}"


def test_a_confirmed_absent_journal_is_still_a_recorded_result(profile, dirs):
    res, _, lines = run(profile, dirs, RecordingOps(script(dirs, journal=False)))
    assert res.exit_code == 0 and any("wrote no persistent journal" in ln for ln in lines)


def test_a_failed_unmount_is_a_nonzero_exit_that_says_the_mount_is_active(profile, dirs):
    mnt, _ = dirs
    s = script(dirs)
    s[f"umount {mnt}"] = OpFailed(["umount"], 32, "target is busy")
    res, _, lines = run(profile, dirs, RecordingOps(s))
    assert res.exit_code != 0
    assert any("still mounted" in ln or "still active" in ln for ln in lines)


def test_the_tmpfs_check_runs_before_any_directory_is_created(profile, tmp_path):
    mnt, out = tmp_path / "mnt", tmp_path / "deep" / "out"
    (tmp_path / "deep").mkdir()
    s = script((mnt, out), outfs="btrfs\n")
    del s[f"findmnt -no FSTYPE -T {out}"]
    s[f"findmnt -no FSTYPE -T {tmp_path / 'deep'}"] = "btrfs\n"
    made = []
    res = run_readback(
        RecordingOps(s), profile, mount_dir=str(mnt), out_dir=str(out), reference_boot_order="0001,0002,0003",
        copier=lambda a, b: None, list_logs=lambda m: [], makedirs=lambda p, **k: made.append(p), out=lambda x: None,
    )
    assert res.exit_code == 1
    assert made == [] and not mnt.exists() and not out.exists()


# ----------------------------------------------------------------- task 5.40


def _run_state(state_dir, phase="table-writing"):
    s = statemod.create_run(
        state_dir, run_id="r1", profile_hash="p", plan_hash="q", board_identity={}, image_roles=[], arm=False
    )
    if phase != "planned":
        statemod.transition(s, phase)


def _tree_with_journal(dirs, size=1000):
    mnt, out = dirs
    (mnt / "log" / "journal").mkdir(parents=True)
    (mnt / "log" / "journal" / "a.journal").write_bytes(b"x" * size)


@pytest.mark.parametrize("phase", ["table-writing", "planned"])
def test_a_run_in_a_non_terminal_phase_refuses_readback_before_any_call(profile, dirs, tmp_path, phase):
    sd = tmp_path / "state"
    _run_state(sd, phase)
    ops = RecordingOps(script(dirs))
    res, copies, lines = run(profile, dirs, ops, state_dir=str(sd))
    assert res.exit_code == 1
    assert ops.log == [] and copies == []
    assert any("r1" in ln and phase in ln for ln in lines), lines


def test_a_finished_run_does_not_block_readback(profile, dirs, tmp_path):
    sd = tmp_path / "state"
    _run_state(sd, "failed")
    ops = RecordingOps(script(dirs))
    res, _, _ = run(profile, dirs, ops, state_dir=str(sd))
    assert res.exit_code == 0
    assert any(c.startswith("mount ") for c in ops.log)


def test_an_unreadable_run_state_is_not_examined_and_mounts_nothing(profile, dirs, tmp_path):
    sd = tmp_path / "state"
    sd.mkdir()
    (sd / "current").write_text("r1\n")
    ops = RecordingOps(script(dirs))
    res, _, lines = run(profile, dirs, ops, state_dir=str(sd))
    assert res.exit_code == 2 and ops.log == []
    assert any("TARGET NOT EXAMINED" in ln for ln in lines)


def test_a_held_on_board_flash_lock_refuses_readback_before_any_call(profile, dirs, tmp_path):
    sd = tmp_path / "state"
    with statemod.OnBoardLock(sd / statemod.LOCK_NAME, run_id="writer"):
        ops = RecordingOps(script(dirs))
        res, copies, lines = run(profile, dirs, ops, state_dir=str(sd))
    assert res.exit_code == 1
    assert ops.log == [] and copies == []
    assert any("lock" in ln for ln in lines), lines


def test_readback_releases_the_flash_lock_when_it_finishes(profile, dirs, tmp_path):
    sd = tmp_path / "state"
    res, _, _ = run(profile, dirs, RecordingOps(script(dirs)), state_dir=str(sd))
    assert res.exit_code == 0
    with statemod.OnBoardLock(sd / statemod.LOCK_NAME):
        pass


def test_a_mount_directory_that_is_already_a_mountpoint_is_refused_without_stacking(profile, dirs):
    mnt, _ = dirs
    ops = RecordingOps(script(dirs))
    res, copies, lines = run(profile, dirs, ops, is_mountpoint=lambda p: p == str(mnt))
    assert res.exit_code == 1 and copies == []
    assert not any(c.startswith(("mount ", "umount ")) for c in ops.log)
    assert any("already a mount point" in ln for ln in lines), lines


def test_the_mount_directory_is_created_private(profile, dirs):
    mnt, _ = dirs
    old = os.umask(0o022)
    try:
        res, _, _ = run(profile, dirs, RecordingOps(script(dirs)), makedirs=os.makedirs)
    finally:
        os.umask(old)
    assert res.exit_code == 0
    assert stat.S_IMODE(os.stat(mnt).st_mode) == 0o700


def test_the_untrusted_mount_carries_ro_nosuid_nodev_noexec(profile, dirs):
    ops = RecordingOps(script(dirs))
    run(profile, dirs, ops)
    mounts = [c.vector for c in ops.calls if c.vector[0] == "mount"]
    assert len(mounts) == 1 and mounts[0][1] == "-o"
    assert sorted(mounts[0][2].split(",")) == ["nodev", "noexec", "nosuid", "ro"]


def test_tree_size_sums_regular_files_and_never_follows_a_symlink(tree):
    from avocado_flash_remote.cmd_readback import _tree_size

    mnt, _, outside = tree
    (outside / "big").write_bytes(b"x" * 100000)
    (mnt / "log" / "journal" / "biglink").symlink_to(outside / "big")
    (mnt / "log" / "journal" / "bigdirlink").symlink_to(outside)
    size = _tree_size([str(mnt / "log" / "journal")])
    assert size == 2  # a.journal (1) + sub/b.journal (1); the links count for nothing
    assert _tree_size([str(mnt / "log" / "does-not-exist")]) == 0


def test_a_journal_larger_than_the_free_space_is_refused_and_unmounted(profile, dirs):
    mnt, out = dirs
    _tree_with_journal(dirs, size=1000)
    ops = RecordingOps(script(dirs))
    res, copies, lines = run(profile, dirs, ops, free_bytes=lambda p: 1500, reserve=1000, cap=10**9)
    assert res.exit_code == 1 and copies == []
    assert ops.log[-1] == f"umount {mnt}"
    assert not out.exists(), "the empty output directory is removed"
    assert any("too large" in ln or "exceeds" in ln for ln in lines), lines


def test_a_journal_that_fits_is_copied(profile, dirs):
    _tree_with_journal(dirs, size=1000)
    res, copies, _ = run(profile, dirs, RecordingOps(script(dirs)), free_bytes=lambda p: 3000, reserve=1000, cap=10**9)
    assert res.exit_code == 0 and copies


def test_a_journal_over_the_fixed_cap_is_refused_even_with_ample_space(profile, dirs):
    _tree_with_journal(dirs, size=1000)
    res, copies, _ = run(profile, dirs, RecordingOps(script(dirs)), free_bytes=lambda p: 10**12, reserve=0, cap=999)
    assert res.exit_code == 1 and copies == []


def test_the_cleanup_lines_name_the_output_directory_too(profile, dirs):
    _, out = dirs
    _, _, lines = run(profile, dirs, RecordingOps(script(dirs)))
    assert any(ln.strip().startswith("rm ") and str(out) in ln for ln in lines), lines


def test_a_copier_that_runs_out_of_space_is_exit_1_with_a_message_and_no_partial_output(profile, dirs):
    mnt, out = dirs
    calls = []

    def copier(src, dst):
        calls.append(dst)
        if len(calls) == 2:
            (out / "partial").write_text("half")
            raise OSError(errno.ENOSPC, "No space left on device")

    ops = RecordingOps(script(dirs))
    mnt_, out_ = dirs
    res = run_readback(
        ops, profile, mount_dir=str(mnt_), out_dir=str(out_), reference_boot_order="0001,0002,0003",
        copier=copier, list_logs=lambda m: [f"{m}/log/boot.log"], out=lambda x: None,
    )  # fmt: skip
    text = "\n".join(res.lines)
    assert res.exit_code == 1
    assert "ERROR: copy from /dev/mmcblk0p16 failed after 1 file(s): " in text
    assert "No space left on device" in text
    assert not out.exists()
    assert ops.log[-1] == f"umount {mnt}"
    assert "cleanup commands" in text


def test_a_readback_error_during_the_copy_is_exit_1_too(profile, dirs):
    mnt, out = dirs

    def copier(src, dst):
        raise ReadbackError("refusing to read outside the mount")

    ops = RecordingOps(script(dirs))
    res = run_readback(
        ops, profile, mount_dir=str(mnt), out_dir=str(out), reference_boot_order="0001,0002,0003",
        copier=copier, list_logs=lambda m: [], out=lambda x: None,
    )  # fmt: skip
    assert res.exit_code == 1 and not out.exists()
    assert ops.log[-1] == f"umount {mnt}"


def test_same_basename_boot_logs_keep_their_relative_paths(profile, dirs):
    mnt, out = dirs
    res, copies, lines = run(
        profile, dirs, RecordingOps(script(dirs)),
        list_logs=lambda m: [f"{m}/log/emmc-test.log", f"{m}/emmc-test.log"],
    )  # fmt: skip
    dests = sorted(d for _, d in copies if not d.endswith("/journal"))
    assert dests == [f"{out}/emmc-test.log", f"{out}/log/emmc-test.log"]
    assert any("copied 2 boot log file(s)" in ln for ln in lines)


def test_two_logs_that_would_land_on_one_destination_are_refused(profile, dirs):
    mnt, out = dirs
    res, copies, lines = run(
        profile, dirs, RecordingOps(script(dirs)),
        list_logs=lambda m: [f"{m}/emmc-test.log", f"{m}/emmc-test.log"],
    )  # fmt: skip
    assert res.exit_code == 1
    assert any("collision" in ln for ln in lines), lines


def test_the_real_copier_creates_the_parent_of_a_nested_log(tree):
    mnt, out, _ = tree
    copy = make_guarded_copier(str(out), str(mnt), lambda n: None)
    copy(str(mnt / "log" / "boot.log"), str(out / "log" / "boot.log"))
    assert (out / "log" / "boot.log").read_text() == "log"
