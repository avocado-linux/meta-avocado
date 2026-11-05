"""Prove the tegra suite's guards fire and the deploy_tree fixture is sound."""

import json
import os
import pathlib
import socket
import stat
import subprocess

import pytest

from avocado_flash_tegra import InputInfo, Problem, format_problems

REMOTE_TESTS = pathlib.Path(__file__).resolve().parents[1] / "remote"
DIR_KEYS = {"tegraflash_bsp", "tegraflash_engine", "tegraflash_tools", "tegraflash_carrier_bsp"}


def test_socket_connect_fails_the_test():
    with pytest.raises(pytest.fail.Exception, match="network connection attempted"):
        socket.socket().connect(("127.0.0.1", 9))


def test_socket_connect_ex_fails_the_test():
    with pytest.raises(pytest.fail.Exception, match="network connection attempted"):
        socket.socket().connect_ex(("127.0.0.1", 9))


@pytest.mark.parametrize(
    "call",
    [
        lambda: subprocess.run(["true"]),
        lambda: subprocess.Popen(["true"]),
        lambda: subprocess.call(["true"]),
        lambda: subprocess.check_output(["true"]),
        lambda: os.system("true"),
    ],
    ids=["run", "Popen", "call", "check_output", "os_system"],
)
def test_subprocess_without_marker_fails_the_test(call):
    with pytest.raises(pytest.fail.Exception, match="real_subprocess"):
        call()


@pytest.mark.real_subprocess
def test_subprocess_with_marker_is_allowed():
    assert subprocess.run(["true"]).returncode == 0
    assert os.system("true") == 0


def test_no_module_shares_a_basename_with_the_remote_suite():
    here = pathlib.Path(__file__).parent
    # conftest.py is exempt: pytest loads it per directory, not by basename.
    mine = {p.name for p in here.glob("*.py")} - {"conftest.py"}
    theirs = {p.name for p in REMOTE_TESTS.glob("*.py")} - {"conftest.py"}
    assert mine & theirs == set()


def test_deploy_tree_image_names_all_come_from_the_real_template(deploy_tree):
    real = json.loads(deploy_tree.real_template.read_text())
    images = real["storage_devices"]["rootdisk"]["images"]
    named = {v for v in images.values() if isinstance(v, str)}
    on_disk = {p.name for p in deploy_tree.images_dir.iterdir()}
    copied = json.loads(deploy_tree.template.read_text())
    assert copied == real
    assert named <= on_disk
    expected_extras = {
        deploy_tree.template.name,
        "Image",
        "stone-provision-tegraflash.sh",
    }
    assert on_disk == named | expected_extras


def test_deploy_tree_files_and_directories(deploy_tree):
    images = json.loads(deploy_tree.template.read_text())["storage_devices"]["rootdisk"]["images"]
    for key, name in images.items():
        if not isinstance(name, str):
            continue
        path = deploy_tree.images_dir / name
        if key in DIR_KEYS:
            assert path.is_dir(), key
        else:
            assert path.is_file() and path.stat().st_size > 0, key
    assert (deploy_tree.images_dir / "Image").stat().st_size > 0
    initrd = deploy_tree.tools_dir / "initrd-flash"
    assert initrd.stat().st_mode & stat.S_IXUSR


@pytest.mark.real_subprocess
def test_deploy_tree_stub_script_is_builtins_only_and_records(deploy_tree, tmp_path):
    script = deploy_tree.script
    assert script.read_text().splitlines()[0] == "#!/bin/sh"
    assert script.stat().st_mode & stat.S_IXUSR
    record = tmp_path / "record"
    env = {"STUB_RECORD": str(record), "PATH": "/nonexistent", "MARK": "xyz"}
    proc = _run_real(script, ["a", "b"], env, tmp_path)
    assert proc == 0
    text = record.read_text()
    assert "MARK" in text and "xyz" in text
    assert "a" in text and "b" in text
    assert str(tmp_path) in text


def _run_real(script, args, env, cwd):
    return subprocess.run([str(script), *args], env=env, cwd=cwd).returncode


def test_format_problems_appends_the_build_target():
    out = format_problems(
        [
            Problem("var image x.btrfs is missing", "avocado-image-var"),
            Problem("something else", None),
        ]
    )
    lines = out.splitlines()
    assert len(lines) == 2
    assert "var image x.btrfs is missing" in lines[0]
    assert "avocado-image-var" in lines[0]
    assert "something else" in lines[1]
    assert "build" not in lines[1].lower()


def test_input_info_is_a_frozen_record():
    info = InputInfo(name="n", key="k", size=3, mtime=1.5)
    assert (info.name, info.key, info.size, info.mtime) == ("n", "k", 3, 1.5)
    with pytest.raises(AttributeError):  # frozen dataclass
        info.size = 4
    assert info.size == 3
