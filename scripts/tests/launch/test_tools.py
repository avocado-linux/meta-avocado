import os
import stat
from pathlib import Path

import pytest

from avocado_flash_launch.envmap import LauncherError
from avocado_flash_launch.tools import (
    check_tegra_tools,
    find_stone,
    make_sysroot_lookup,
)


def _exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _sysroot(tmp_path: Path, tools=("stone", "fwup")) -> Path:
    root = tmp_path / "work/x/avocado-stone/1.0/recipe-sysroot-native"
    for t in tools:
        _exe(root / "usr/bin" / t)
    (root / "usr/lib").mkdir(parents=True, exist_ok=True)
    return root


def test_sysroot_stone_wins_over_host_stone(tmp_path):
    root = _sysroot(tmp_path)
    which = lambda name: "/usr/bin/stone" if name == "stone" else None
    stone, env = find_stone(lambda tool: root, which, base_path="/usr/bin:/bin")
    assert stone == root / "usr/bin/stone"
    assert env["PATH"] == f"{root}/usr/bin:/usr/bin:/bin"
    assert env["LD_LIBRARY_PATH"] == f"{root}/usr/lib"


def test_host_stone_used_only_when_sysroot_has_none():
    which = lambda name: "/opt/bin/stone" if name == "stone" else None
    stone, env = find_stone(lambda tool: None, which, base_path="/usr/bin")
    assert stone == Path("/opt/bin/stone")
    assert env == {}


def test_neither_place_refuses_naming_stone_both_places_and_setting():
    with pytest.raises(LauncherError) as exc:
        find_stone(lambda tool: None, lambda name: None)
    msg = str(exc.value)
    assert "stone" in msg
    assert "native sysroot" in msg
    assert "PATH" in msg
    assert "rm_work" in msg


def test_refusal_creates_no_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    before = sorted(p.name for p in tmp_path.iterdir())
    with pytest.raises(LauncherError):
        find_stone(lambda tool: None, lambda name: None)
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_lookup_finds_sysroot_from_deploy_path(tmp_path):
    root = _sysroot(tmp_path)
    deploy = tmp_path / "deploy/images/qemux86-64"
    deploy.mkdir(parents=True)
    lookup = make_sysroot_lookup(deploy)
    assert lookup("stone") == root
    assert lookup("nothere") is None


def test_lookup_ignores_non_executable(tmp_path):
    root = _sysroot(tmp_path, tools=())
    p = root / "usr/bin/stone"
    p.parent.mkdir(parents=True)
    p.write_text("x")
    p.chmod(0o644)
    deploy = tmp_path / "deploy/images/m"
    deploy.mkdir(parents=True)
    assert make_sysroot_lookup(deploy)("stone") is None


ALL = {"python3", "fdtget", "fdtput", "cpp", "lsusb"}


def test_tegra_tools_all_present_passes():
    check_tegra_tools(lambda n: f"/usr/bin/{n}" if n in ALL else None, (3, 10))


@pytest.mark.parametrize("missing", sorted(ALL))
def test_tegra_missing_tool_refused_by_name(missing):
    which = lambda n: None if n == missing else f"/usr/bin/{n}"
    with pytest.raises(LauncherError) as exc:
        check_tegra_tools(which, (3, 12))
    assert missing in str(exc.value)


def test_tegra_old_python_refused():
    with pytest.raises(LauncherError) as exc:
        check_tegra_tools(lambda n: f"/usr/bin/{n}", (3, 9))
    assert "3.10" in str(exc.value)


def test_tegra_unreadable_python_version_refused():
    with pytest.raises(LauncherError):
        check_tegra_tools(lambda n: f"/usr/bin/{n}", None)


def test_tegra_reports_every_problem():
    with pytest.raises(LauncherError) as exc:
        check_tegra_tools(lambda n: None, None)
    msg = str(exc.value)
    for t in ALL:
        assert t in msg
