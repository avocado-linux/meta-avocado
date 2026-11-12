import pytest

from avocado_flash_launch import envmap
from avocado_flash_launch.envmap import LauncherError, LaunchOpts, build_run_env, map_profile


def opts(**kw):
    base = dict(medium="sd")
    base.update(kw)
    return LaunchOpts(**base)


@pytest.mark.parametrize(
    "medium,boot,profile",
    [
        ("sd", "nvme", "sd"),
        ("emmc", "nvme", "uuu-emmc"),
        ("ums", "nvme", "ums"),
        ("nvme", "nvme", "tegraflash-nvme"),
        ("nvme", "sd", "tegraflash-sd"),
        ("nvme", "emmc", "tegraflash-emmc"),
    ],
)
def test_map_profile(medium, boot, profile):
    assert map_profile(medium, boot) == profile


def test_map_profile_unknown_medium_refused():
    with pytest.raises(LauncherError):
        map_profile("fuse-srk", "nvme")


def test_force_zero_without_yes_and_inherited_force_replaced_with_warning():
    env, warns = build_run_env(opts(), {"AVOCADO_PROVISION_FORCE": "1"}, "sd")
    assert env["AVOCADO_PROVISION_FORCE"] == "0"
    assert len(warns) == 1
    assert "AVOCADO_PROVISION_FORCE" in warns[0] and "1" in warns[0]


def test_force_one_with_yes():
    env, warns = build_run_env(opts(assume_yes=True), {}, "sd")
    assert env["AVOCADO_PROVISION_FORCE"] == "1"
    assert warns == []


def test_equal_inherited_value_no_warning():
    env, warns = build_run_env(opts(), {"AVOCADO_PROVISION_FORCE": "0"}, "sd")
    assert env["AVOCADO_PROVISION_FORCE"] == "0"
    assert warns == []


def test_inherited_dry_run_dropped_with_warning():
    env, warns = build_run_env(opts(), {"AVOCADO_PROVISION_DRY_RUN": "1"}, "sd")
    assert "AVOCADO_PROVISION_DRY_RUN" not in env
    assert len(warns) == 1
    assert "AVOCADO_PROVISION_DRY_RUN" in warns[0] and "'1'" in warns[0]


def test_dry_run_option_sets_one():
    env, warns = build_run_env(opts(dry_run=True), {}, "sd")
    assert env["AVOCADO_PROVISION_DRY_RUN"] == "1"
    assert warns == []


def test_task_sd_only():
    env, _ = build_run_env(opts(task="upgrade"), {}, "sd")
    assert env["AVOCADO_PROVISION_FWUP_TASK"] == "upgrade"
    env, _ = build_run_env(opts(medium="emmc", task="upgrade"), {}, "uuu-emmc")
    assert "AVOCADO_PROVISION_FWUP_TASK" not in env


def test_device_passed_and_inherited_device_replaced():
    env, warns = build_run_env(
        opts(device="/dev/sdb"), {"AVOCADO_PROVISION_DEVICE": "/dev/sda"}, "sd"
    )
    assert env["AVOCADO_PROVISION_DEVICE"] == "/dev/sdb"
    assert any("/dev/sda" in w for w in warns)


def test_inherited_device_dropped_when_none_given():
    env, warns = build_run_env(opts(), {"AVOCADO_PROVISION_DEVICE": "/dev/sda"}, "sd")
    assert "AVOCADO_PROVISION_DEVICE" not in env
    assert any("/dev/sda" in w for w in warns)


def test_nvme_only_options():
    o = opts(medium="nvme", kernel_cmdline_extra="a=b", rcm_id="0955:7523")
    env, _ = build_run_env(o, {}, "tegraflash-nvme", kernel_image="/img/Image")
    assert env["AVOCADO_KERNEL_CMDLINE_EXTRA"] == "a=b"
    assert env["AVOCADO_PROVISION_RCM_ID"] == "0955:7523"
    assert env["AVOCADO_PROVISION_KERNEL_IMAGE"] == "/img/Image"
    assert env["AVOCADO_PROVISION_PROFILE"] == "tegraflash-nvme"
    env, _ = build_run_env(
        opts(medium="sd", kernel_cmdline_extra="a=b", rcm_id="0955:7523"), {}, "sd"
    )
    assert "AVOCADO_KERNEL_CMDLINE_EXTRA" not in env
    assert "AVOCADO_PROVISION_RCM_ID" not in env


def test_kernel_image_not_passed_for_non_jetson():
    env, _ = build_run_env(opts(), {"AVOCADO_PROVISION_KERNEL_IMAGE": "/x"}, "sd", kernel_image="/img/Image")
    assert "AVOCADO_PROVISION_KERNEL_IMAGE" not in env


def test_inherited_profile_replaced():
    env, warns = build_run_env(opts(), {"AVOCADO_PROVISION_PROFILE": "ums"}, "sd")
    assert env["AVOCADO_PROVISION_PROFILE"] == "sd"
    assert any("ums" in w for w in warns)


def test_other_environment_kept_and_input_not_mutated():
    inherited = {"PATH": "/bin", "AVOCADO_PROVISION_FORCE": "1"}
    env, _ = build_run_env(opts(), inherited, "sd")
    assert env["PATH"] == "/bin"
    assert inherited == {"PATH": "/bin", "AVOCADO_PROVISION_FORCE": "1"}


def test_bmaptool_refused_first_even_with_bad_ums_device():
    with pytest.raises(LauncherError, match="bmaptool is no longer offered"):
        build_run_env(opts(medium="ums", device="/dev/sdb", backend="bmaptool"), {}, "ums")


def test_ums_device_refused():
    with pytest.raises(LauncherError, match="ums"):
        build_run_env(opts(medium="ums", device="/dev/sdb"), {}, "ums")


def test_owned_variables_listed():
    assert "AVOCADO_PROVISION_FORCE" in envmap.OWNED_VARS
    assert len(envmap.OWNED_VARS) == 8


def test_exported_device_sets_device_for_ums():
    env, _ = build_run_env(opts(medium="ums", exported_device="/dev/sdb"), {}, "ums")
    assert env["AVOCADO_PROVISION_DEVICE"] == "/dev/sdb"


def test_exported_device_with_user_device_for_ums_still_refused():
    with pytest.raises(LauncherError, match="ums"):
        build_run_env(opts(medium="ums", device="/dev/sdc", exported_device="/dev/sdb"), {}, "ums")


@pytest.mark.parametrize("medium,profile", [("sd", "sd"), ("emmc", "uuu-emmc"), ("nvme", "tegraflash-nvme")])
def test_exported_device_refused_for_other_media(medium, profile):
    with pytest.raises(LauncherError, match="exported"):
        build_run_env(opts(medium=medium, exported_device="/dev/sdb"), {}, profile)


def test_inherited_device_replaced_and_warned_for_ums():
    env, warns = build_run_env(
        opts(medium="ums", exported_device="/dev/sdb"), {"AVOCADO_PROVISION_DEVICE": "/dev/sda"}, "ums"
    )
    assert env["AVOCADO_PROVISION_DEVICE"] == "/dev/sdb"
    assert any("AVOCADO_PROVISION_DEVICE" in w and "/dev/sda" in w for w in warns)
