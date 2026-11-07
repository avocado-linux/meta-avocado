"""Erase flags and the final initrd-flash call."""


import pytest

from avocado_tegraflash import EngineError, Media
from avocado_tegraflash.flash import erase_flags, run_flash


def flags(media, emmc=False, nvme=False, only=False):
    return erase_flags(media, erase_nvme=nvme, erase_emmc=emmc, erase_only=only)


def test_nvme_media_gives_only_erase_nvme():
    assert flags(Media.NVME) == ["--erase-nvme"]


@pytest.mark.parametrize("media", [Media.EMMC, Media.SD])
def test_emmc_and_sd_media_give_no_flags(media):
    assert flags(media) == []


def test_erase_emmc_and_only_on_nvme_are_alphabetical():
    assert flags(Media.NVME, emmc=True, only=True) == [
        "--erase-emmc",
        "--erase-nvme",
        "--erase-only",
    ]


def test_erase_nvme_variable_on_nvme_media_is_not_duplicated():
    assert flags(Media.NVME, nvme=True) == ["--erase-nvme"]


def test_erase_nvme_variable_on_emmc_media_adds_the_flag():
    assert flags(Media.EMMC, nvme=True) == ["--erase-nvme"]


def test_all_variables_on_sd_media_are_alphabetical():
    assert flags(Media.SD, emmc=True, nvme=True, only=True) == [
        "--erase-emmc",
        "--erase-nvme",
        "--erase-only",
    ]


def test_erase_only_alone_on_emmc_gives_only_that_flag():
    assert flags(Media.EMMC, only=True) == ["--erase-only"]


def test_flags_are_a_new_list_each_call():
    first = flags(Media.NVME)
    first.append("--junk")
    assert flags(Media.NVME) == ["--erase-nvme"]


class Rec:
    def __init__(self, status=0):
        self.status = status
        self.calls = []

    def run(self, argv, *, cwd=None, env=None):
        self.calls.append((list(argv), cwd, env))
        return self.status


def make_tool(tmp_path, mode=0o755):
    tool = tmp_path / "initrd-flash"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(mode)
    return tool


def test_run_flash_runs_tool_in_work_dir_with_flags_and_env(tmp_path):
    make_tool(tmp_path)
    rec = Rec()
    env = {"PATH": "/x"}
    assert run_flash(rec, tmp_path, ["--erase-nvme"], env) == 0
    assert rec.calls == [(["./initrd-flash", "--erase-nvme"], tmp_path, env)]


def test_run_flash_with_no_flags_passes_bare_tool(tmp_path):
    make_tool(tmp_path)
    rec = Rec()
    run_flash(rec, tmp_path, [], {})
    assert rec.calls[0][0] == ["./initrd-flash"]


def test_run_flash_returns_tool_status_unchanged(tmp_path):
    make_tool(tmp_path)
    assert run_flash(Rec(7), tmp_path, [], {}) == 7


@pytest.mark.parametrize("status", [0, 1, 7, 255])
def test_run_flash_passes_ordinary_exit_statuses_through(tmp_path, status):
    make_tool(tmp_path)
    assert run_flash(Rec(status), tmp_path, [], {}) == status


@pytest.mark.parametrize("status,expected", [(-9, 137), (-15, 143), (-2, 130)])
def test_run_flash_maps_a_signal_death_to_128_plus_the_signal(tmp_path, status, expected):
    make_tool(tmp_path)
    assert run_flash(Rec(status), tmp_path, [], {}) == expected


@pytest.mark.real_subprocess
def test_run_flash_reports_a_real_child_killed_by_sigkill_as_137(tmp_path):
    from avocado_tegraflash.runner import SubprocessRunner

    tool = tmp_path / "initrd-flash"
    tool.write_text("#!/bin/sh\nkill -9 $$\n")
    tool.chmod(0o755)
    assert run_flash(SubprocessRunner(), tmp_path, [], {"PATH": "/usr/bin:/bin"}) == 137


def test_run_flash_missing_tool_raises_listing_directory(tmp_path):
    (tmp_path / "marker-file.txt").write_text("x")
    rec = Rec()
    with pytest.raises(EngineError) as exc:
        run_flash(rec, tmp_path, [], {})
    assert "initrd-flash" in str(exc.value)
    assert "marker-file.txt" in str(exc.value)
    assert rec.calls == []


def test_run_flash_non_executable_tool_raises(tmp_path):
    make_tool(tmp_path, mode=0o644)
    rec = Rec()
    with pytest.raises(EngineError):
        run_flash(rec, tmp_path, [], {})
    assert rec.calls == []


def test_mutant_unsorted_flags_is_detected(tmp_path, mutant):
    mod = mutant("flash.py", "sorted(found)", "list(found)")
    got = mod.erase_flags(Media.NVME, erase_nvme=False, erase_emmc=True, erase_only=True)
    assert got != ["--erase-emmc", "--erase-nvme", "--erase-only"]


def test_mutant_signal_status_unmapped_is_detected(tmp_path, mutant):
    mod = mutant("flash.py", "128 - status", "status")
    make_tool(tmp_path)
    assert mod.run_flash(Rec(-9), tmp_path, [], {}) != 137


def test_mutant_status_swallowed_is_detected(tmp_path, mutant):
    mod = mutant("flash.py", "return status", "return 0")
    make_tool(tmp_path)
    assert mod.run_flash(Rec(7), tmp_path, [], {}) == 0
