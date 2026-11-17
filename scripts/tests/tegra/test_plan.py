from pathlib import Path

import pytest

from avocado_flash_tegra import FlashError
from avocado_flash_tegra.plan import Invocation, build_invocation, describe, safe_path

EXPECTED_KEYS = {
    "AVOCADO_STONE_MANIFEST",
    "AVOCADO_STONE_DATA_DIR",
    "AVOCADO_STONE_BUILD_DIR",
    "AVOCADO_PROVISION_PROFILE",
    "AVOCADO_PROVISION_KERNEL_IMAGE",
    "AVOCADO_PROVISION_FORCE",
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
    assert inv.argv[-1] == "./provision.sh"
    assignments = inv.argv[4:-1]
    assert sorted(assignments) == sorted(f"{k}={v}" for k, v in inv.env.items())


def test_root_caller_gets_script_argv_and_env_dict():
    inv = make(is_root=True, have_sudo=False)
    assert inv.argv == ("/deploy/images/provision.sh",)
    assert set(inv.env) == EXPECTED_KEYS


def test_provision_force_is_exported_for_root_and_once_in_the_sudo_argv():
    root = make(is_root=True, have_sudo=False)
    assert root.env["AVOCADO_PROVISION_FORCE"] == "1"
    sudo = make()
    assert sudo.env["AVOCADO_PROVISION_FORCE"] == "1"
    assert sudo.argv.count("AVOCADO_PROVISION_FORCE=1") == 1
    assert sudo.argv.index("AVOCADO_PROVISION_FORCE=1") < len(sudo.argv) - 1
    assert sum(a.startswith("AVOCADO_PROVISION_FORCE=") for a in sudo.argv) == 1


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


def test_sudo_argv_names_the_script_relative_to_cwd_when_the_path_has_an_equals_sign():
    # env reads any operand containing "=" as another assignment, runs nothing
    # and exits 0.
    inv = make(
        images_dir=Path("/deploy=x/images"),
        script=Path("/deploy=x/images/provision.sh"),
    )
    command = inv.argv[-1]
    assert "=" not in command
    assert command == "./provision.sh"
    assert inv.cwd == Path("/deploy=x/images")


def test_sudo_argv_refuses_a_script_outside_cwd_with_an_equals_sign():
    with pytest.raises(FlashError, match="="):
        make(script=Path("/elsewhere=x/provision.sh"))


def test_sudo_argv_keeps_an_absolute_script_outside_cwd_without_an_equals_sign():
    inv = make(script=Path("/elsewhere/provision.sh"))
    assert inv.argv[-1] == "/elsewhere/provision.sh"


def test_sudo_argv_refuses_a_script_name_with_an_equals_sign():
    with pytest.raises(FlashError):
        make(script=Path("/deploy/images/a=b.sh"))


def test_root_argv_keeps_the_absolute_script_path():
    inv = make(
        is_root=True,
        have_sudo=False,
        images_dir=Path("/deploy=x/images"),
        script=Path("/deploy=x/images/provision.sh"),
    )
    assert inv.argv == ("/deploy=x/images/provision.sh",)


def _path_entries(inv):
    return inv.env["PATH"].split(":")


def test_relative_and_empty_caller_path_components_are_dropped():
    inv = make(caller_path="/usr/bin::.:rel/bin:/opt/x:")
    assert _path_entries(inv) == ["/helpers", "/usr/bin", "/opt/x"]


def test_dropped_components_are_absent_from_the_sudo_env_assignment_too():
    inv = make(caller_path="/usr/bin::.:rel/bin")
    assignment = next(a for a in inv.argv if a.startswith("PATH="))
    assert assignment == "PATH=/helpers:/usr/bin"


@pytest.mark.parametrize("caller", ["", ":", "rel:.:", "::"])
def test_a_caller_path_with_nothing_absolute_falls_back_to_the_system_path(caller):
    inv = make(caller_path=caller, extra_path_dir=Path("/tools"))
    assert _path_entries(inv) == [
        "/helpers",
        "/tools",
        "/usr/local/sbin",
        "/usr/local/bin",
        "/usr/sbin",
        "/usr/bin",
        "/sbin",
        "/bin",
    ]


def test_safe_path_keeps_only_absolute_components_in_order():
    assert safe_path("/b::.:/a:rel") == "/b:/a"
    assert safe_path("") == "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def test_profile_argument_selects_the_provisioning_profile():
    assert make(profile="tegraflash-sd").env["AVOCADO_PROVISION_PROFILE"] == "tegraflash-sd"


def test_profile_defaults_to_nvme():
    assert make().env["AVOCADO_PROVISION_PROFILE"] == "tegraflash-nvme"


def test_cmdline_extra_is_added_as_one_variable_with_the_exact_value():
    value = "systemd.mask=a.service systemd.mask=b.service"
    inv = make(cmdline_extra=value)
    assert inv.env["AVOCADO_KERNEL_CMDLINE_EXTRA"] == value
    assert set(inv.env) == EXPECTED_KEYS | {"AVOCADO_KERNEL_CMDLINE_EXTRA"}


def test_cmdline_extra_survives_sudo_env_as_a_single_operand_with_its_spaces():
    value = "systemd.mask=a.service systemd.mask=b.service"
    inv = make(cmdline_extra=value)
    assert f"AVOCADO_KERNEL_CMDLINE_EXTRA={value}" in inv.argv


def test_cmdline_extra_is_absent_by_default():
    assert "AVOCADO_KERNEL_CMDLINE_EXTRA" not in make().env


def test_cmdline_extra_is_exported_to_the_script_when_root():
    inv = make(is_root=True, cmdline_extra="quiet")
    assert inv.env["AVOCADO_KERNEL_CMDLINE_EXTRA"] == "quiet"
    assert inv.argv == ("/deploy/images/provision.sh",)
