"""Tests for the executable, helper, mkbootimg and host tool checks."""

import json
import os

import pytest

from avocado_flash_tegra import prereqs

HELPER_REL = (
    "meta-avocado-nvidia/recipes-avocado/sdk/avocado-sdk-target/avocado-tegra-bootimg"
)
HOST_TOOLS = ("jq", "fdtget", "fdtput", "cpp", "lsusb")


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


def test_all_host_tools_present_has_no_problems(tmp_path):
    assert prereqs.check_host_tools(path=_bin_with(tmp_path, HOST_TOOLS)) == []


def test_one_missing_host_tool_names_only_it(tmp_path):
    names = [t for t in HOST_TOOLS if t != "fdtput"]
    problems = prereqs.check_host_tools(path=_bin_with(tmp_path, names))
    assert len(problems) == 1
    assert "fdtput" in problems[0].what
    assert "fdtget" not in problems[0].what


def test_two_missing_host_tools_name_both(tmp_path):
    names = [t for t in HOST_TOOLS if t not in ("jq", "lsusb")]
    problems = prereqs.check_host_tools(path=_bin_with(tmp_path, names))
    assert len(problems) == 2
    text = " ".join(p.what for p in problems)
    assert "jq" in text and "lsusb" in text


def test_path_argument_restricts_the_lookup(tmp_path, monkeypatch):
    real_dir = _bin_with(tmp_path, HOST_TOOLS)
    monkeypatch.setenv("PATH", real_dir)
    empty = tmp_path / "emptybin"
    empty.mkdir()
    problems = prereqs.check_host_tools(path=str(empty))
    assert len(problems) == len(HOST_TOOLS)


def test_default_path_is_the_process_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", _bin_with(tmp_path, HOST_TOOLS))
    assert prereqs.check_host_tools() == []
    monkeypatch.setenv("PATH", os.fspath(tmp_path / "nowhere"))
    assert len(prereqs.check_host_tools()) == len(HOST_TOOLS)
