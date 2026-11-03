from pathlib import Path

import pytest

from avocado_flash_tegra import FlashError
from avocado_flash_tegra.plan import Invocation, build_invocation, describe

EXPECTED_KEYS = {
    "AVOCADO_STONE_MANIFEST",
    "AVOCADO_STONE_DATA_DIR",
    "AVOCADO_STONE_BUILD_DIR",
    "AVOCADO_PROVISION_PROFILE",
    "AVOCADO_PROVISION_KERNEL_IMAGE",
    "PATH",
}


def make(**over):
    kw = dict(
        images_dir=Path("/deploy/images"),
        manifest=Path("/deploy/images/manifest.json"),
        script=Path("/deploy/images/provision.sh"),
        build_dir=Path("/var/tmp/work"),
        kernel_image=Path("/deploy/images/Image"),
        helper_dir=Path("/helpers"),
        extra_path_dir=None,
        is_root=False,
        have_sudo=True,
        caller_path="/usr/bin:/bin",
    )
    kw.update(over)
    return build_invocation(**kw)


def test_five_variables_and_path_present_with_exact_values():
    inv = make()
    assert isinstance(inv, Invocation)
    assert set(inv.env) == EXPECTED_KEYS
    assert inv.env["AVOCADO_STONE_MANIFEST"] == "/deploy/images/manifest.json"
    assert inv.env["AVOCADO_STONE_DATA_DIR"] == "/deploy/images"
    assert inv.env["AVOCADO_STONE_BUILD_DIR"] == "/var/tmp/work"
    assert inv.env["AVOCADO_PROVISION_PROFILE"] == "tegraflash-nvme"
    assert inv.env["AVOCADO_PROVISION_KERNEL_IMAGE"] == "/deploy/images/Image"
    assert inv.cwd == Path("/deploy/images")


def test_helper_directory_first_in_path():
    inv = make()
    assert inv.env["PATH"] == "/helpers:/usr/bin:/bin"


def test_extra_path_dir_between_helper_and_caller_path():
    inv = make(extra_path_dir=Path("/tools"))
    assert inv.env["PATH"] == "/helpers:/tools:/usr/bin:/bin"


def test_non_root_caller_gets_sudo_argv_with_explicit_assignments():
    inv = make()
    assert inv.argv[:4] == ("sudo", "env", "-u", "AVOCADO_AGENT_SOCK")
    assert inv.argv[-1] == "/deploy/images/provision.sh"
    assignments = inv.argv[4:-1]
    assert sorted(assignments) == sorted(f"{k}={v}" for k, v in inv.env.items())


def test_root_caller_gets_script_argv_and_env_dict():
    inv = make(is_root=True, have_sudo=False)
    assert inv.argv == ("/deploy/images/provision.sh",)
    assert set(inv.env) == EXPECTED_KEYS


def test_root_caller_does_not_use_sudo_even_when_available():
    inv = make(is_root=True, have_sudo=True)
    assert inv.argv == ("/deploy/images/provision.sh",)


def test_neither_root_nor_sudo_raises_naming_root():
    with pytest.raises(FlashError) as exc:
        make(is_root=False, have_sudo=False)
    assert "root" in str(exc.value)


def test_agent_sock_in_caller_environment_absent_from_result(monkeypatch):
    monkeypatch.setenv("AVOCADO_AGENT_SOCK", "/run/agent.sock")
    for kw in (dict(), dict(is_root=True, have_sudo=False)):
        inv = make(**kw)
        assert "AVOCADO_AGENT_SOCK" not in inv.env
        assert not any("/run/agent.sock" in a for a in inv.argv)
        assert not any(a.startswith("AVOCADO_AGENT_SOCK=") for a in inv.argv)


def test_agent_sock_unset_in_sudo_argv_via_env_u():
    inv = make()
    i = inv.argv.index("-u")
    assert inv.argv[i + 1] == "AVOCADO_AGENT_SOCK"


def test_agent_sock_in_caller_path_value_does_not_add_variable(monkeypatch):
    monkeypatch.setenv("AVOCADO_AGENT_SOCK", "x")
    inv = make(is_root=True, have_sudo=False)
    assert "AVOCADO_AGENT_SOCK" not in inv.env


def test_unrelated_caller_variable_does_not_leak(monkeypatch):
    monkeypatch.setenv("SECRET_X", "hunter2")
    inv = make()
    assert "SECRET_X" not in inv.env
    assert not any("hunter2" in a for a in inv.argv)


def test_describe_shows_command_variables_and_paths():
    text = describe(make())
    assert "sudo" in text
    assert "provision.sh" in text
    for key in EXPECTED_KEYS:
        assert key in text
    assert "/deploy/images" in text
    assert "/helpers" in text


def test_describe_root_has_no_sudo():
    text = describe(make(is_root=True, have_sudo=False))
    assert "sudo" not in text
    assert "provision.sh" in text
