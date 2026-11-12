"""Tests for avocado_tegraflash.env: the oracle's environment handling."""

import dataclasses

import pytest

from avocado_tegraflash import EngineError
from avocado_tegraflash.env import Config, from_environ

REQUIRED = (
    "AVOCADO_STONE_MANIFEST",
    "AVOCADO_STONE_BUILD_DIR",
    "AVOCADO_STONE_DATA_DIR",
)


@pytest.fixture(autouse=True)
def _machine(monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "aarch64")


def base():
    return {
        "AVOCADO_STONE_MANIFEST": "/m/manifest.json",
        "AVOCADO_STONE_BUILD_DIR": "/b",
        "AVOCADO_STONE_DATA_DIR": "/d",
    }


def cfg(**extra):
    env = base()
    env.update(extra)
    return from_environ(env)


def test_required_variables_are_read_verbatim():
    c = cfg()
    assert (c.manifest, c.build_dir, c.data_dir) == ("/m/manifest.json", "/b", "/d")


@pytest.mark.parametrize("name", REQUIRED)
def test_missing_required_variable_raises_naming_it(name):
    env = base()
    del env[name]
    with pytest.raises(EngineError, match=name):
        from_environ(env)


@pytest.mark.parametrize("name", REQUIRED)
def test_empty_required_variable_raises_naming_it(name):
    env = base()
    env[name] = ""
    with pytest.raises(EngineError, match=name):
        from_environ(env)


def test_empty_data_dir_is_refused():
    with pytest.raises(EngineError, match="AVOCADO_STONE_DATA_DIR"):
        cfg(AVOCADO_STONE_DATA_DIR="")


def test_optional_defaults_match_the_oracle():
    c = cfg()
    assert (
        c.sdk_prefix,
        c.sdk_arch,
        c.cc,
        c.profile,
        c.sd_device,
        c.kernel_image,
        c.kernel_version,
        c.kernel_cmdline,
        c.kernel_cmdline_extra,
        c.boardctl_target,
        c.boardctl_serial,
        c.pythonwarnings,
        c.home,
    ) == (
        "",
        "aarch64",
        "",
        "tegraflash",
        "",
        "",
        "?",
        "",
        "",
        "",
        "",
        "ignore::SyntaxWarning",
        "/root",
    )


def test_sdk_arch_default_uses_platform_machine(monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "ppc64le")
    assert from_environ(base()).sdk_arch == "ppc64le"


def test_explicit_sdk_arch_beats_machine():
    assert cfg(AVOCADO_SDK_ARCH="x86_64").sdk_arch == "x86_64"


def test_empty_optional_falls_back_like_shell_default_expansion():
    c = cfg(
        AVOCADO_SDK_ARCH="",
        AVOCADO_PROVISION_PROFILE="",
        AVOCADO_PROVISION_KERNEL_VERSION="",
        HOME="",
        PYTHONWARNINGS="",
    )
    assert (c.sdk_arch, c.profile, c.kernel_version, c.home, c.pythonwarnings) == (
        "aarch64",
        "tegraflash",
        "?",
        "/root",
        "ignore::SyntaxWarning",
    )


def test_optional_values_are_read_from_the_environment():
    c = cfg(
        AVOCADO_SDK_PREFIX="/sdk",
        CC="gcc -m64",
        AVOCADO_PROVISION_PROFILE="nvme",
        AVOCADO_PROVISION_SD_DEVICE="/dev/sdz",
        AVOCADO_PROVISION_KERNEL_IMAGE="/k/Image",
        AVOCADO_PROVISION_KERNEL_VERSION="6.6",
        AVOCADO_KERNEL_CMDLINE="quiet",
        AVOCADO_KERNEL_CMDLINE_EXTRA="debug",
        BOARDCTL_TARGET="t1",
        BOARDCTL_SERIAL="s1",
        PYTHONWARNINGS="error",
        HOME="/home/u",
    )
    assert (c.sdk_prefix, c.cc, c.profile, c.sd_device, c.kernel_image) == (
        "/sdk",
        "gcc -m64",
        "nvme",
        "/dev/sdz",
        "/k/Image",
    )
    assert (c.kernel_version, c.kernel_cmdline, c.kernel_cmdline_extra) == (
        "6.6",
        "quiet",
        "debug",
    )
    assert (c.boardctl_target, c.boardctl_serial, c.pythonwarnings, c.home) == (
        "t1",
        "s1",
        "error",
        "/home/u",
    )


@pytest.mark.parametrize("name", ["ERASE_NVME", "ERASE_EMMC", "ERASE_ONLY"])
def test_erase_flags_default_false(name):
    assert getattr(cfg(), name.lower()) is False


@pytest.mark.parametrize("name", ["ERASE_NVME", "ERASE_EMMC", "ERASE_ONLY"])
def test_erase_flag_is_true_for_exactly_one(name):
    assert getattr(cfg(**{name: "1"}), name.lower()) is True


@pytest.mark.parametrize("value", ["true", "0", "yes", " 1", "1 ", "01", "", "TRUE", "١"])
@pytest.mark.parametrize("name", ["ERASE_NVME", "ERASE_EMMC", "ERASE_ONLY"])
def test_erase_flag_is_false_for_anything_but_exactly_one(name, value):
    assert getattr(cfg(**{name: value}), name.lower()) is False


def test_erase_flags_are_independent():
    c = cfg(ERASE_EMMC="1")
    assert (c.erase_nvme, c.erase_emmc, c.erase_only) == (False, True, False)


def test_config_is_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg().manifest = "/other"


def test_from_environ_does_not_mutate_the_mapping():
    env = base()
    before = dict(env)
    from_environ(env)
    assert env == before


def test_config_type_is_exported():
    assert isinstance(cfg(), Config)


CMDLINE_VARS = ("AVOCADO_KERNEL_CMDLINE", "AVOCADO_KERNEL_CMDLINE_EXTRA")


@pytest.mark.deviation("cmdline-control-chars-refused")
@pytest.mark.parametrize("name", CMDLINE_VARS)
@pytest.mark.parametrize("bad", ["a\nb", "a\tb", "a\x00b", "a\x1fb", "a\x7fb", "a\r"])
def test_cmdline_control_character_is_refused_naming_the_variable(name, bad):
    with pytest.raises(EngineError, match=name):
        cfg(**{name: bad})


@pytest.mark.parametrize("name", CMDLINE_VARS)
@pytest.mark.parametrize("ok", ["console=ttyTCU0,115200 quiet", "", "a  b é"])
def test_cmdline_plain_or_empty_value_passes_unchanged(name, ok):
    field = {"AVOCADO_KERNEL_CMDLINE": "kernel_cmdline", "AVOCADO_KERNEL_CMDLINE_EXTRA": "kernel_cmdline_extra"}[name]
    assert getattr(cfg(**{name: ok}), field) == ok
