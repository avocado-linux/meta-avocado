"""Tests for the executable, helper, mkbootimg and host tool checks."""

import json
import os

import pytest

from avocado_flash_tegra import prereqs

HELPER_REL = (
    "meta-avocado-nvidia/recipes-avocado/sdk/avocado-sdk-target/avocado-tegra-bootimg"
)
HOST_TOOLS = ("python3", "fdtget", "fdtput", "cpp", "lsusb")


@pytest.fixture
def template(deploy_tree):
    return json.loads(deploy_tree.template.read_text())


def _exe(path, mode=0o755):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(mode)
    return path


def _targets(problems):
    return [p.target for p in problems]


def test_check_executables_clean_tree_has_no_problems(deploy_tree, template):
    assert prereqs.check_executables(deploy_tree.images_dir, template) == []


def test_script_mode_0644_is_reported_against_avocado_stone(deploy_tree, template):
    deploy_tree.script.chmod(0o644)
    problems = prereqs.check_executables(deploy_tree.images_dir, template)
    assert _targets(problems) == ["avocado-stone"]
    assert "stone-provision-tegraflash.sh" in problems[0].what


def test_script_absent_is_reported_against_avocado_stone(deploy_tree, template):
    deploy_tree.script.unlink()
    problems = prereqs.check_executables(deploy_tree.images_dir, template)
    assert _targets(problems) == ["avocado-stone"]


def test_tools_dir_without_initrd_flash_is_reported(deploy_tree, template):
    (deploy_tree.tools_dir / "initrd-flash").unlink()
    problems = prereqs.check_executables(deploy_tree.images_dir, template)
    assert _targets(problems) == ["tegraflash-tools-deploy"]
    assert "initrd-flash" in problems[0].what


def test_initrd_flash_not_executable_is_reported(deploy_tree, template):
    (deploy_tree.tools_dir / "initrd-flash").chmod(0o644)
    problems = prereqs.check_executables(deploy_tree.images_dir, template)
    assert _targets(problems) == ["tegraflash-tools-deploy"]


def test_kernel_image_absent_says_boot_image_cannot_pin_rootfs(deploy_tree, template):
    deploy_tree.kernel_image.unlink()
    problems = prereqs.check_executables(deploy_tree.images_dir, template)
    assert len(problems) == 1
    assert "Image" in problems[0].what
    assert "rootfs" in problems[0].what


def test_kernel_image_empty_is_reported(deploy_tree, template):
    deploy_tree.kernel_image.write_bytes(b"")
    problems = prereqs.check_executables(deploy_tree.images_dir, template)
    assert len(problems) == 1
    assert "Image" in problems[0].what


def test_two_failures_are_both_reported(deploy_tree, template):
    deploy_tree.script.chmod(0o644)
    deploy_tree.kernel_image.unlink()
    problems = prereqs.check_executables(deploy_tree.images_dir, template)
    assert len(problems) == 2


def _make_helper(layer_root, text, mode):
    helper = layer_root / HELPER_REL
    helper.parent.mkdir(parents=True)
    helper.write_text(text)
    helper.chmod(mode)
    return helper


def test_helper_mode_0644_with_sh_shebang_is_accepted(tmp_path):
    helper = _make_helper(tmp_path, "#!/bin/sh\necho hi\n", 0o644)
    assert prereqs.find_bootimg_helper(tmp_path) == helper


def test_helper_mode_0755_with_sh_shebang_is_accepted(tmp_path):
    helper = _make_helper(tmp_path, "#!/bin/sh\necho hi\n", 0o755)
    assert prereqs.find_bootimg_helper(tmp_path) == helper


def test_helper_absent_returns_none(tmp_path):
    assert prereqs.find_bootimg_helper(tmp_path) is None


def test_helper_with_other_first_line_returns_none(tmp_path):
    _make_helper(tmp_path, "#!/usr/bin/env python3\nprint(1)\n", 0o644)
    assert prereqs.find_bootimg_helper(tmp_path) is None


def test_helper_shebang_not_on_first_line_returns_none(tmp_path):
    _make_helper(tmp_path, "\n#!/bin/sh\n", 0o644)
    assert prereqs.find_bootimg_helper(tmp_path) is None


def test_helper_that_is_a_directory_returns_none(tmp_path):
    (tmp_path / HELPER_REL).mkdir(parents=True)
    assert prereqs.find_bootimg_helper(tmp_path) is None


def test_helper_problem_none_says_image_would_not_name_rootfs():
    problem = prereqs.helper_problem(None)
    assert problem is not None
    assert "rootfs" in problem.what
    assert "avocado-tegra-bootimg" in problem.what


def test_helper_problem_present_returns_none(tmp_path):
    helper = _make_helper(tmp_path, "#!/bin/sh\n", 0o644)
    assert prereqs.helper_problem(helper) is None


def test_mkbootimg_only_in_tools_dir_returns_that_dir(deploy_tree, tmp_path):
    _exe(deploy_tree.tools_dir / "mkbootimg")
    empty = tmp_path / "emptybin"
    empty.mkdir()
    problems, extra = prereqs.check_mkbootimg(deploy_tree.images_dir, path=str(empty))
    assert problems == []
    assert extra == deploy_tree.tools_dir


def test_mkbootimg_only_on_search_path_needs_no_extra_dir(deploy_tree, tmp_path):
    bindir = tmp_path / "bin"
    _exe(bindir / "mkbootimg")
    problems, extra = prereqs.check_mkbootimg(deploy_tree.images_dir, path=str(bindir))
    assert problems == []
    assert extra is None


def test_mkbootimg_in_neither_place_is_a_problem_naming_it(deploy_tree, tmp_path):
    empty = tmp_path / "emptybin"
    empty.mkdir()
    problems, extra = prereqs.check_mkbootimg(deploy_tree.images_dir, path=str(empty))
    assert extra is None
    assert len(problems) == 1
    assert "mkbootimg" in problems[0].what


def test_mkbootimg_non_executable_in_tools_dir_does_not_count(deploy_tree, tmp_path):
    _exe(deploy_tree.tools_dir / "mkbootimg", mode=0o644)
    empty = tmp_path / "emptybin"
    empty.mkdir()
    problems, extra = prereqs.check_mkbootimg(deploy_tree.images_dir, path=str(empty))
    assert len(problems) == 1
    assert extra is None


def test_mkbootimg_in_both_places_prefers_path_and_adds_nothing(deploy_tree, tmp_path):
    _exe(deploy_tree.tools_dir / "mkbootimg")
    bindir = tmp_path / "bin"
    _exe(bindir / "mkbootimg")
    problems, extra = prereqs.check_mkbootimg(deploy_tree.images_dir, path=str(bindir))
    assert problems == []
    assert extra is None


def _bin_with(tmp_path, names):
    bindir = tmp_path / "hostbin"
    for name in names:
        _exe(bindir / name)
    return str(bindir)


def _ver(major, minor):
    return lambda path: (major, minor)


def test_host_tools_are_python3_fdtget_fdtput_cpp_lsusb():
    assert prereqs.HOST_TOOLS == ("python3", "fdtget", "fdtput", "cpp", "lsusb")


def test_all_host_tools_present_has_no_problems(tmp_path):
    path = _bin_with(tmp_path, HOST_TOOLS)
    assert prereqs.check_host_tools(path=path, version_of=_ver(3, 10)) == []


def test_missing_jq_alone_does_not_refuse(tmp_path):
    path = _bin_with(tmp_path, HOST_TOOLS)
    assert not (tmp_path / "hostbin" / "jq").exists()
    assert prereqs.check_host_tools(path=path, version_of=_ver(3, 12)) == []


def test_one_missing_host_tool_names_only_it(tmp_path):
    names = [t for t in HOST_TOOLS if t != "fdtput"]
    problems = prereqs.check_host_tools(path=_bin_with(tmp_path, names), version_of=_ver(3, 10))
    assert len(problems) == 1
    assert "fdtput" in problems[0].what
    assert "fdtget" not in problems[0].what


def test_missing_python3_and_cpp_are_both_named(tmp_path):
    names = [t for t in HOST_TOOLS if t not in ("python3", "cpp")]
    problems = prereqs.check_host_tools(path=_bin_with(tmp_path, names), version_of=_ver(3, 10))
    text = " ".join(p.what for p in problems)
    assert len(problems) == 2
    assert "python3" in text and "cpp" in text
    assert "jq" not in text


def test_python3_missing_and_cpp_missing_refuse_in_one_message(tmp_path):
    from avocado_flash_tegra import format_problems

    names = [t for t in HOST_TOOLS if t not in ("python3", "cpp")]
    problems = prereqs.check_host_tools(path=_bin_with(tmp_path, names), version_of=_ver(3, 10))
    message = format_problems(problems)
    assert message.count("python3") >= 1 and message.count("cpp") >= 1
    assert "jq" not in message


def test_python3_39_refuses_naming_found_and_needed(tmp_path):
    problems = prereqs.check_host_tools(path=_bin_with(tmp_path, HOST_TOOLS), version_of=_ver(3, 9))
    assert len(problems) == 1
    assert "3.9" in problems[0].what and "3.10" in problems[0].what


def test_python3_310_is_accepted(tmp_path):
    assert prereqs.check_host_tools(path=_bin_with(tmp_path, HOST_TOOLS), version_of=_ver(3, 10)) == []


def test_python3_2_refuses(tmp_path):
    problems = prereqs.check_host_tools(path=_bin_with(tmp_path, HOST_TOOLS), version_of=_ver(2, 7))
    assert len(problems) == 1
    assert "2.7" in problems[0].what


def test_python3_4_0_is_accepted(tmp_path):
    assert prereqs.check_host_tools(path=_bin_with(tmp_path, HOST_TOOLS), version_of=_ver(4, 0)) == []


def test_unreadable_python3_version_refuses(tmp_path):
    problems = prereqs.check_host_tools(path=_bin_with(tmp_path, HOST_TOOLS), version_of=lambda path: None)
    assert len(problems) == 1
    assert "python3" in problems[0].what and "3.10" in problems[0].what


def test_version_is_read_from_the_python3_found_on_the_given_path(tmp_path):
    path = _bin_with(tmp_path, HOST_TOOLS)
    seen = []

    def fake(found):
        seen.append(found)
        return (3, 11)

    prereqs.check_host_tools(path=path, version_of=fake)
    assert seen == [os.path.join(path, "python3")]


def test_version_is_not_read_when_python3_is_missing(tmp_path):
    names = [t for t in HOST_TOOLS if t != "python3"]
    seen = []
    prereqs.check_host_tools(path=_bin_with(tmp_path, names), version_of=lambda p: seen.append(p))
    assert seen == []


@pytest.mark.real_subprocess
def test_default_version_reader_reports_the_real_interpreter():
    import sys

    assert prereqs.python_version(sys.executable) == sys.version_info[:2]


@pytest.mark.real_subprocess  # lifts the autouse fake; run itself is replaced below
def test_version_probe_runs_the_interpreter_isolated(monkeypatch):
    """The shim runs `python3 -I` as root; the probe must see the same interpreter."""
    seen = []

    def fake_run(argv, **kwargs):
        seen.append(list(argv))
        kwargs["stdout"].write(b"3.12\n")
        return prereqs.subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(prereqs.subprocess, "run", fake_run)
    assert prereqs.python_version("/stub/python3") == (3, 12)
    assert seen[0][:2] == ["/stub/python3", "-I"]


@pytest.mark.real_subprocess
def test_default_version_reader_returns_none_for_a_non_interpreter(tmp_path):
    fake = _exe(tmp_path / "python3")
    assert prereqs.python_version(os.fspath(fake)) is None


@pytest.mark.real_subprocess
def test_default_version_reader_returns_none_for_a_missing_file(tmp_path):
    assert prereqs.python_version(os.fspath(tmp_path / "nope")) is None


def test_path_argument_restricts_the_lookup(tmp_path, monkeypatch):
    real_dir = _bin_with(tmp_path, HOST_TOOLS)
    monkeypatch.setenv("PATH", real_dir)
    empty = tmp_path / "emptybin"
    empty.mkdir()
    problems = prereqs.check_host_tools(path=str(empty), version_of=_ver(3, 10))
    assert len(problems) == len(HOST_TOOLS)


def test_default_path_is_the_process_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", _bin_with(tmp_path, HOST_TOOLS))
    assert prereqs.check_host_tools(version_of=_ver(3, 10)) == []
    monkeypatch.setenv("PATH", os.fspath(tmp_path / "nowhere"))
    assert len(prereqs.check_host_tools(version_of=_ver(3, 10))) == len(HOST_TOOLS)


def test_check_mkbootimg_looks_in_the_tools_directory_the_template_names(deploy_tree, tmp_path):
    _exe(deploy_tree.images_dir / "custom-tools" / "mkbootimg")
    empty = tmp_path / "empty"
    empty.mkdir()
    problems, extra = prereqs.check_mkbootimg(
        deploy_tree.images_dir, path=str(empty), tools_dirname="custom-tools"
    )
    assert problems == []
    assert extra == deploy_tree.images_dir / "custom-tools"


def test_missing_script_key_is_a_problem_naming_the_key_and_target(deploy_tree, template):
    del template["provision"]["profiles"]["tegraflash-nvme"]["script"]
    problems = prereqs.check_executables(deploy_tree.images_dir, template)
    assert [p.target for p in problems] == ["avocado-stone"]
    assert "script" in problems[0].what


def test_missing_tools_key_is_a_problem_naming_the_key_and_target(deploy_tree, template):
    del template["storage_devices"]["rootdisk"]["images"]["tegraflash_tools"]
    problems = prereqs.check_executables(deploy_tree.images_dir, template)
    assert [p.target for p in problems] == ["avocado-stone"]
    assert "tegraflash_tools" in problems[0].what


def _mutated_prereqs(tmp_path, old, new):
    import importlib
    import shutil
    import sys

    src = os.path.dirname(prereqs.__file__)
    root = tmp_path / "mut"
    dest = root / "avocado_flash_tegra"
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__"))
    target = dest / "prereqs.py"
    text = target.read_text()
    assert text.count(old) == 1
    target.write_text(text.replace(old, new))
    saved = {k: v for k, v in sys.modules.items() if k.startswith("avocado_flash_tegra")}
    for k in saved:
        del sys.modules[k]
    sys.path.insert(0, os.fspath(root))
    try:
        return importlib.import_module("avocado_flash_tegra.prereqs"), saved
    finally:
        sys.path.remove(os.fspath(root))


@pytest.mark.parametrize(
    "old,new,scenario",
    [
        ('HOST_TOOLS = ("python3", ', 'HOST_TOOLS = ("jq", "python3", ', "jq_required"),
        ("< MIN_PYTHON", "< (3, 9)", "python39_accepted"),
    ],
)
def test_mutated_prereqs_are_caught_by_the_expectations(tmp_path, old, new, scenario):
    import sys

    mutated, saved = _mutated_prereqs(tmp_path, old, new)
    try:
        path = _bin_with(tmp_path, HOST_TOOLS)
        if scenario == "jq_required":
            assert mutated.check_host_tools(path=path, version_of=_ver(3, 12)) != []
        else:
            assert mutated.check_host_tools(path=path, version_of=_ver(3, 9)) == []
    finally:
        for k in [k for k in sys.modules if k.startswith("avocado_flash_tegra")]:
            del sys.modules[k]
        sys.modules.update(saved)


def test_python_floor_agrees_with_the_provisioning_shim():
    import pathlib
    import re

    repo_root = pathlib.Path(__file__).resolve().parents[3]
    shim = repo_root / "meta-avocado-nvidia" / "stone" / "tegra" / "stone-provision-tegraflash.sh"
    floors = re.findall(r"sys\.version_info < \((\d+), (\d+)\)", shim.read_text())
    assert len(floors) == 1, "the shim must state its python floor exactly once"
    assert tuple(int(p) for p in floors[0]) == prereqs.MIN_PYTHON


def test_script_name_reads_the_requested_profile(template):
    assert prereqs.script_name(template, "tegraflash-sd") == prereqs.script_name(template)
    del template["provision"]["profiles"]["tegraflash-sd"]["script"]
    assert prereqs.script_name(template, "tegraflash-sd") is None
    assert prereqs.script_name(template) is not None
