"""The engine keeps only absolute PATH components, once, before any tool lookup."""

import os
from pathlib import Path

from avocado_tegraflash.cli import main
from test_cli_flow import make_rig

SDK_CPP = "x86_64-avocadosdk-linux-cpp"
# The host wrapper's fallback (scripts/avocado_flash_tegra/plan.py SYSTEM_PATH).
SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def _marker_tool(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    tool = directory / name
    tool.write_text("#!/bin/sh\nexit 0\n")
    tool.chmod(0o755)
    return tool


def _flash_path(rig) -> list:
    (flash,) = rig.runner.named("initrd-flash")
    return flash.env["PATH"].split(":")


def test_relative_directory_ahead_of_an_absolute_one_resolves_the_absolute_cpp(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _marker_tool(tmp_path / "rel", SDK_CPP)
    rig = make_rig(tmp_path)
    rig.environ["PATH"] = f"rel:{rig.stub_dir}:/usr/bin:/bin"
    rc, _, _ = rig.go(main, capsys)
    assert (rc, str(rig.stub_dir / SDK_CPP) in rig.runner.wrapper_text, "rel/" in rig.runner.wrapper_text) == (
        0,
        True,
        False,
    )


def test_empty_component_never_resolves_a_tool_in_the_working_directory(tmp_path, capsys, monkeypatch):
    cwd = tmp_path / "cwd"
    _marker_tool(cwd, SDK_CPP)
    monkeypatch.chdir(cwd)
    rig = make_rig(tmp_path)
    rig.environ["PATH"] = f":{rig.stub_dir}:/usr/bin:/bin"
    rc, _, _ = rig.go(main, capsys)
    assert (rc, str(rig.stub_dir / SDK_CPP) in rig.runner.wrapper_text, str(cwd) in rig.runner.wrapper_text) == (
        0,
        True,
        False,
    )


def test_flash_environment_path_holds_only_absolute_components(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rig = make_rig(tmp_path)
    rig.environ["PATH"] = f":rel:{rig.stub_dir}::./bin:/usr/bin:/bin:"
    rc, _, _ = rig.go(main, capsys)
    parts = _flash_path(rig)
    assert (rc, [p for p in parts if not os.path.isabs(p)]) == (0, [])


def test_flash_environment_keeps_the_absolute_components_in_order(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rig = make_rig(tmp_path)
    rig.environ["PATH"] = f"rel:{rig.stub_dir}::/usr/bin:/bin"
    rig.go(main, capsys)
    # The first two entries are the cpp wrapper directory and the work directory.
    assert _flash_path(rig)[2:] == [str(rig.stub_dir), "/usr/bin", "/bin"]


def test_dropped_components_are_logged_by_name(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rig = make_rig(tmp_path)
    rig.environ["PATH"] = f"rel:{rig.stub_dir}::./bin:/usr/bin"
    _, out, err = rig.go(main, capsys)
    line = next(l for l in (out + err).splitlines() if "PATH" in l and "dropped" in l)
    assert ("'rel'" in line, "'./bin'" in line, "''" in line) == (True, True, True)


def test_an_all_absolute_path_logs_nothing_about_dropping(tmp_path, capsys):
    rig = make_rig(tmp_path)
    _, out, err = rig.go(main, capsys)
    assert [l for l in (out + err).splitlines() if "dropped" in l] == []


def test_no_absolute_component_falls_back_to_the_system_path(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rig = make_rig(tmp_path)
    rig.environ["PATH"] = "rel::./bin"
    rig.go(main, capsys)
    assert _flash_path(rig)[2:] == SYSTEM_PATH.split(":")
