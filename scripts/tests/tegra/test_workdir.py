"""Tests for the work directory, free-space check and cleanup."""

import datetime
import os
import pathlib
import stat
from collections import namedtuple
from types import SimpleNamespace

import pytest

from avocado_flash_tegra import FlashError, InputInfo
from avocado_flash_tegra import workdir

Usage = namedtuple("Usage", "total used free")


class FakeRunner:
    def __init__(self, returncode=0, on_capture=None):
        self.calls = []
        self.returncode = returncode
        self.on_capture = on_capture

    def capture(self, argv):
        self.calls.append(list(argv))
        if self.on_capture:
            self.on_capture(argv)
        return self.returncode, ""


def _info(size):
    return InputInfo(name="x", key="k", size=size, mtime=0.0)


def _usage_recorder(free):
    seen = []

    def disk_usage(path):
        seen.append(pathlib.Path(path))
        return Usage(free * 2, free, free)

    return disk_usage, seen


def test_required_bytes_adds_one_tenth_rounded_up():
    assert workdir.required_bytes([_info(100), _info(5)]) == 116


def test_required_bytes_exact_tenth_is_not_rounded():
    assert workdir.required_bytes([_info(1000)]) == 1100


def test_required_bytes_empty_is_zero():
    assert workdir.required_bytes([]) == 0


def test_planned_workdir_returns_explicit_path_untouched(tmp_path):
    explicit = tmp_path / "mine"
    assert workdir.planned_workdir(explicit, "avocado-m") == explicit
    assert not explicit.exists()


def test_planned_workdir_makes_a_relative_explicit_path_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = workdir.planned_workdir(pathlib.Path("rel/work"), "avocado-m")
    assert path == tmp_path / "rel" / "work"
    assert path.is_absolute()


def test_planned_workdir_makes_a_relative_default_base_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    now = datetime.datetime(2026, 11, 3, 4, 5, 6)
    path = workdir.planned_workdir(None, "avocado-m", base=pathlib.Path("rel"), now=now)
    assert path.is_absolute()
    assert path == tmp_path / "rel" / "avocado-flash-avocado-m-20261103-040506"


def test_planned_workdir_default_name_and_no_creation(tmp_path):
    now = datetime.datetime(2026, 11, 3, 4, 5, 6)
    path = workdir.planned_workdir(None, "avocado-m", base=tmp_path, now=now)
    assert path == tmp_path / "avocado-flash-avocado-m-20261103-040506"
    assert not path.exists()


def test_require_space_equal_to_need_passes(tmp_path):
    du, _ = _usage_recorder(500)
    workdir.require_space(tmp_path, 500, disk_usage=du)


def test_require_space_one_byte_less_refuses(tmp_path):
    du, _ = _usage_recorder(499)
    with pytest.raises(FlashError):
        workdir.require_space(tmp_path, 500, disk_usage=du)


def test_refusal_states_both_sizes(tmp_path):
    du, _ = _usage_recorder(1234)
    with pytest.raises(FlashError) as exc:
        workdir.require_space(tmp_path, 99999, disk_usage=du)
    text = str(exc.value)
    assert "99999" in text
    assert "1234" in text


def test_missing_path_is_measured_on_nearest_existing_ancestor_and_not_created(tmp_path):
    target = tmp_path / "a" / "b" / "work"
    du, seen = _usage_recorder(10)
    workdir.require_space(target, 5, disk_usage=du)
    assert seen == [tmp_path]
    assert not (tmp_path / "a").exists()


def test_existing_path_is_measured_itself(tmp_path):
    du, seen = _usage_recorder(10)
    workdir.require_space(tmp_path, 5, disk_usage=du)
    assert seen == [tmp_path]


def test_create_new_directory_is_mode_0700_and_tool_created(tmp_path):
    wd = workdir.create_workdir(tmp_path / "w")
    assert wd.created_by_tool is True
    assert wd.path == tmp_path / "w"
    assert wd.log == tmp_path / "w" / "flash.log"
    assert stat.S_IMODE(os.stat(wd.path).st_mode) == 0o700


def test_create_missing_nested_path_creates_it(tmp_path):
    wd = workdir.create_workdir(tmp_path / "a" / "w")
    assert wd.path.is_dir()
    assert wd.created_by_tool is True
    assert stat.S_IMODE(os.stat(wd.path).st_mode) == 0o700


def test_create_existing_directory_is_used_as_is(tmp_path):
    os.chmod(tmp_path, 0o755)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions - test builds an unsafe directory on purpose
    wd = workdir.create_workdir(tmp_path)
    assert wd.created_by_tool is False
    assert stat.S_IMODE(os.stat(tmp_path).st_mode) == 0o755


def test_success_removes_created_directory_as_root(tmp_path):
    wd = workdir.create_workdir(tmp_path / "w")
    (wd.path / "tegraflash").mkdir()
    (wd.path / "tegraflash" / "f").write_text("x")
    runner = FakeRunner()
    assert workdir.cleanup(wd, True, runner, is_root=True) is None
    assert not wd.path.exists()
    assert runner.calls == []


def test_success_non_root_removes_tegraflash_through_exact_sudo_argv(tmp_path):
    wd = workdir.create_workdir(tmp_path / "w")
    tf = wd.path / "tegraflash"
    tf.mkdir()

    def fake_sudo(argv):
        os.rmdir(argv[-1])

    runner = FakeRunner(on_capture=fake_sudo)
    workdir.cleanup(wd, True, runner, is_root=False)
    assert runner.calls == [["sudo", "rm", "-rf", "--one-file-system", "--", str(tf)]]
    assert not wd.path.exists()


def test_failure_keeps_created_directory_and_returns_path(tmp_path):
    wd = workdir.create_workdir(tmp_path / "w")
    (wd.path / "tegraflash").mkdir()
    runner = FakeRunner()
    assert workdir.cleanup(wd, False, runner, is_root=False) == wd.path
    assert (wd.path / "tegraflash").is_dir()
    assert runner.calls == []


def test_explicit_existing_directory_survives_success(tmp_path):
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("mine")
    wd = workdir.create_workdir(tmp_path)
    (tmp_path / "tegraflash").mkdir()
    workdir.cleanup(wd, True, FakeRunner(), is_root=True)
    assert tmp_path.is_dir()
    assert sentinel.read_text() == "mine"
    assert not (tmp_path / "tegraflash").exists()


def test_explicit_existing_directory_non_root_only_tegraflash_goes_through_sudo(tmp_path):
    wd = workdir.create_workdir(tmp_path)
    tf = tmp_path / "tegraflash"
    tf.mkdir()
    (tmp_path / "keep.txt").write_text("mine")
    runner = FakeRunner(on_capture=lambda argv: os.rmdir(argv[-1]))
    workdir.cleanup(wd, True, runner, is_root=False)
    assert runner.calls == [["sudo", "rm", "-rf", "--one-file-system", "--", str(tf)]]
    assert (tmp_path / "keep.txt").exists()
    assert tmp_path.is_dir()


def test_removal_failure_warns_and_does_not_raise(tmp_path, capsys):
    wd = workdir.create_workdir(tmp_path / "w")
    (wd.path / "tegraflash").mkdir()
    runner = FakeRunner(returncode=1)
    result = workdir.cleanup(wd, True, runner, is_root=False)
    assert result == wd.path
    assert (wd.path / "tegraflash").is_dir()
    assert str(wd.path) in capsys.readouterr().err


def _foreign_owner(path):
    real = os.lstat(path)
    return SimpleNamespace(st_mode=real.st_mode, st_uid=real.st_uid + 1)


def test_create_refuses_an_existing_symlink_to_a_directory(tmp_path):
    target = tmp_path / "real"
    target.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(FlashError, match="symlink|not a directory"):
        workdir.create_workdir(link)


def test_create_refuses_an_existing_directory_writable_by_others(tmp_path):
    wd = tmp_path / "w"
    wd.mkdir()
    os.chmod(wd, 0o770)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions - test builds an unsafe directory on purpose
    with pytest.raises(FlashError, match="writable"):
        workdir.create_workdir(wd)


def test_create_refuses_an_existing_directory_owned_by_someone_else(tmp_path):
    wd = tmp_path / "w"
    wd.mkdir(mode=0o700)
    with pytest.raises(FlashError, match="owned"):
        workdir.create_workdir(wd, stat_fn=_foreign_owner)


def test_create_refuses_an_existing_regular_file(tmp_path):
    f = tmp_path / "f"
    f.write_text("x")
    with pytest.raises(FlashError, match="not a directory"):
        workdir.create_workdir(f)


def test_default_path_is_created_with_mkdir_0700(tmp_path):
    wd = workdir.create_workdir(tmp_path / "d", default=True)
    assert wd.created_by_tool is True
    assert stat.S_IMODE(os.stat(wd.path).st_mode) == 0o700


def test_default_path_that_already_exists_is_never_reused(tmp_path):
    pre = tmp_path / "d"
    pre.mkdir(mode=0o700)
    with pytest.raises(FlashError, match="exists"):
        workdir.create_workdir(pre, default=True)


def test_creation_failure_is_a_flash_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    for default in (False, True):
        with pytest.raises(FlashError):
            workdir.create_workdir(blocker / "w", default=default)


# ---- every ancestor of the work directory is part of the trust boundary ----


def _ancestor_tree(tmp_path, mode):
    ancestor = tmp_path / "anc"
    ancestor.mkdir()
    (ancestor / "mid").mkdir(mode=0o700)
    os.chmod(ancestor, mode)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions - test builds an unsafe directory on purpose
    return ancestor


@pytest.mark.parametrize("mode", [0o770, 0o707, 0o777])
def test_a_group_or_world_writable_ancestor_is_refused_by_name(tmp_path, mode):
    ancestor = _ancestor_tree(tmp_path, mode)
    with pytest.raises(FlashError, match="writable") as exc:
        workdir.create_workdir(ancestor / "mid" / "w")
    assert str(ancestor) in str(exc.value)
    assert not (ancestor / "mid" / "w").exists()


def test_an_existing_work_directory_under_an_unsafe_ancestor_is_refused(tmp_path):
    ancestor = _ancestor_tree(tmp_path, 0o770)
    existing = ancestor / "mid"
    with pytest.raises(FlashError, match="writable") as exc:
        workdir.create_workdir(existing)
    assert str(ancestor) in str(exc.value)


def test_a_default_path_under_an_unsafe_ancestor_is_refused_too(tmp_path):
    ancestor = _ancestor_tree(tmp_path, 0o770)
    with pytest.raises(FlashError, match="writable"):
        workdir.create_workdir(ancestor / "mid" / "w", default=True)
    assert not (ancestor / "mid" / "w").exists()


def test_a_world_writable_sticky_ancestor_is_accepted(tmp_path):
    ancestor = _ancestor_tree(tmp_path, 0o1777)
    wd = workdir.create_workdir(ancestor / "mid" / "w")
    assert wd.created_by_tool is True


def test_an_ancestor_owned_by_someone_else_is_refused_by_name(tmp_path):
    ancestor = _ancestor_tree(tmp_path, 0o755)
    real_lstat = os.lstat

    def stat_fn(path):
        st = real_lstat(path)
        if str(path) == str(ancestor):
            return SimpleNamespace(st_mode=st.st_mode, st_uid=424242)
        return st

    with pytest.raises(FlashError, match="owned") as exc:
        workdir.create_workdir(ancestor / "mid" / "w", stat_fn=stat_fn)
    assert str(ancestor) in str(exc.value)


def test_an_ancestor_owned_by_root_is_accepted(tmp_path):
    ancestor = _ancestor_tree(tmp_path, 0o755)
    real_lstat = os.lstat

    def stat_fn(path):
        st = real_lstat(path)
        if str(path) == str(ancestor):
            return SimpleNamespace(st_mode=st.st_mode, st_uid=0)
        return st

    wd = workdir.create_workdir(ancestor / "mid" / "w", stat_fn=stat_fn)
    assert wd.created_by_tool is True


def test_a_symlinked_ancestor_is_resolved_and_its_target_checked(tmp_path):
    unsafe = _ancestor_tree(tmp_path, 0o770)
    link = tmp_path / "link"
    link.symlink_to(unsafe)
    with pytest.raises(FlashError, match="writable") as exc:
        workdir.create_workdir(link / "mid" / "w")
    assert str(unsafe) in str(exc.value)


def test_a_symlinked_ancestor_to_a_safe_directory_is_accepted(tmp_path):
    safe = _ancestor_tree(tmp_path, 0o755)
    link = tmp_path / "link"
    link.symlink_to(safe)
    wd = workdir.create_workdir(link / "mid" / "w")
    assert (safe / "mid" / "w").is_dir()
    assert wd.created_by_tool is True
