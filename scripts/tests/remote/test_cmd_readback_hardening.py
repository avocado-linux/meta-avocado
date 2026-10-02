"""Readback copies out of an untrusted mounted image with no-follow semantics and fails closed (task 5.33)."""

from __future__ import annotations

import os

import pytest

from test_cmd_readback_status import DISK, PART, dirs, profile, run, script  # noqa: F401
from avocado_flash_remote.cmd_readback import ReadbackError, make_guarded_copier, run_readback, _default_logs
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
