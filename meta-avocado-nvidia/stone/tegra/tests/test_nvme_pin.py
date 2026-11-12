"""NVMe flash target pin: CARRIER_NVME_PCI / AVOCADO_PROVISION_NVME_PCI.

Ports tests/test-nvme-flash-target.sh, which lifts the nvme) branch out of the
legacy script text and cannot run against the engine. The cases are the same,
plus the sed and bash corner cases the shell test does not reach.
"""

from pathlib import Path

import pytest

from avocado_tegraflash import EngineError, Media
from avocado_tegraflash.cli import main
from avocado_tegraflash.env import from_environ
from avocado_tegraflash.plainenv import read_plain_env
from avocado_tegraflash.settings import apply_boot_device, verify_staged_env
from avocado_tegraflash.toolchain import flash_environment
from test_cli_flow import make_rig

ENV_NAME = ".env.initrd-flash"
PLACEHOLDER_ENV = 'BOOTDEV="placeholder"\nROOTFS_DEVICE="placeholder"\nEXTERNAL_ROOTFS_DRIVE=0\n'
NVME_ENV = 'BOOTDEV="nvme0n1p1"\nROOTFS_DEVICE="nvme0n1"\nEXTERNAL_ROOTFS_DRIVE=1\n'
EXPECTED_ERROR = (
    "NVMe flash target '{bad}' is not a PCI address\n"
    "       (dddd:bb:dd.f, e.g. 0005:01:00.0). Check CARRIER_NVME_PCI\n"
    "       in carrier.env or AVOCADO_PROVISION_NVME_PCI."
)


def _work(tmp_path: Path, env: str = PLACEHOLDER_ENV, carrier: str | None = None) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    (work / ENV_NAME).write_text(env)
    if carrier is not None:
        (work / "carrier.env").write_text(carrier)
    return work


def _env(work: Path) -> str:
    return (work / ENV_NAME).read_text()


def _apply(work: Path, nvme_pci: str = "", media: Media = Media.NVME):
    lines: list[str] = []
    apply_boot_device(work, media, sd_device="mmcblk0", nvme_pci=nvme_pci, log=lines.append)
    return lines


# --- unset changes nothing ---


def test_unset_writes_no_pin_and_logs_nothing(tmp_path):
    work = _work(tmp_path)
    assert _apply(work) == []
    assert _env(work) == NVME_ENV


def test_unset_with_a_carrier_env_that_has_no_pin_changes_nothing(tmp_path):
    work = _work(tmp_path, carrier='CARRIER_LABEL="x"\nCARRIER_ENV_A=b\n')
    assert _apply(work) == []
    assert _env(work) == NVME_ENV


def test_empty_carrier_value_counts_as_unset(tmp_path):
    work = _work(tmp_path, carrier='CARRIER_NVME_PCI=""\n')
    assert _apply(work) == []
    assert "ROOTFS_NVME_PCI" not in _env(work)


# --- carrier.env ---


@pytest.mark.parametrize(
    "line",
    [
        'CARRIER_NVME_PCI="0005:01:00.0"',
        "CARRIER_NVME_PCI='0005:01:00.0'",
        "CARRIER_NVME_PCI=0005:01:00.0",
        'CARRIER_NVME_PCI="0005:01:00.0"   ',
        'CARRIER_NVME_PCI="0005:01:00.0"\r',
    ],
)
def test_carrier_value_in_any_quote_form_is_pinned(tmp_path, line):
    work = _work(tmp_path, carrier=line + "\n")
    lines = _apply(work)
    assert lines == ["NVMe flash target: PCIe 0005:01:00.0"]
    assert _env(work) == NVME_ENV + 'ROOTFS_NVME_PCI="0005:01:00.0"\n'


def test_last_matching_carrier_line_wins(tmp_path):
    work = _work(tmp_path, carrier='CARRIER_NVME_PCI="0003:01:00.0"\nX=1\nCARRIER_NVME_PCI="0005:01:00.0"\n')
    _apply(work)
    assert 'ROOTFS_NVME_PCI="0005:01:00.0"' in _env(work)
    assert "0003" not in _env(work)


def test_an_empty_last_line_overrides_an_earlier_pin_like_tail_1(tmp_path):
    work = _work(tmp_path, carrier='CARRIER_NVME_PCI="0003:01:00.0"\nCARRIER_NVME_PCI=\n')
    assert _apply(work) == []
    assert "ROOTFS_NVME_PCI" not in _env(work)


def test_a_line_sed_would_not_match_is_ignored(tmp_path):
    work = _work(tmp_path, carrier=' CARRIER_NVME_PCI=bad\nXCARRIER_NVME_PCI=bad\n#CARRIER_NVME_PCI=bad\nCARRIER_NVME_PCI="0005:01:00.0\'\n')
    # The last line mixes quote kinds, which the sed expression accepts as a pair of optional quotes.
    _apply(work)
    assert 'ROOTFS_NVME_PCI="0005:01:00.0"' in _env(work)


def test_a_value_with_an_inner_quote_does_not_match_so_nothing_is_pinned(tmp_path):
    work = _work(tmp_path, carrier='CARRIER_NVME_PCI="0005:01"00.0"\n')
    assert _apply(work) == []
    assert "ROOTFS_NVME_PCI" not in _env(work)


def test_unquoted_trailing_whitespace_stays_in_the_value_like_the_sed_greedy_group(tmp_path):
    work = _work(tmp_path, carrier="CARRIER_NVME_PCI=0005:01:00.0 \n")
    with pytest.raises(EngineError, match="'0005:01:00.0 ' is not a PCI address"):
        _apply(work)


def test_carrier_env_is_read_only_for_nvme(tmp_path):
    work = _work(tmp_path, carrier="CARRIER_NVME_PCI=garbage\n")
    for media in (Media.EMMC, Media.SD):
        (work / "internal-flash-emmc.xml").write_text("<x/>")
        assert "NVMe" not in "".join(_apply(work, media=media))
    assert "ROOTFS_NVME_PCI" not in _env(work)


# --- override ---


def test_env_override_beats_carrier_env(tmp_path):
    work = _work(tmp_path, carrier='CARRIER_NVME_PCI="0005:01:00.0"\n')
    lines = _apply(work, nvme_pci="0003:01:00.0")
    assert lines == ["NVMe flash target: PCIe 0003:01:00.0"]
    assert _env(work).count("ROOTFS_NVME_PCI") == 1
    assert 'ROOTFS_NVME_PCI="0003:01:00.0"' in _env(work)


def test_an_invalid_carrier_value_is_ignored_when_the_override_is_valid(tmp_path):
    work = _work(tmp_path, carrier="CARRIER_NVME_PCI=nvme1n1\n")
    _apply(work, nvme_pci="0003:01:00.0")
    assert 'ROOTFS_NVME_PCI="0003:01:00.0"' in _env(work)


# --- replace versus append ---


def test_existing_pin_line_is_replaced_in_place(tmp_path):
    work = _work(tmp_path, PLACEHOLDER_ENV + 'ROOTFS_NVME_PCI="0001:01:00.0"\nTAIL=1\n')
    _apply(work, nvme_pci="0005:01:00.0")
    assert _env(work) == NVME_ENV + 'ROOTFS_NVME_PCI="0005:01:00.0"\nTAIL=1\n'


def test_every_existing_pin_line_is_replaced_like_sed(tmp_path):
    work = _work(tmp_path, PLACEHOLDER_ENV + "ROOTFS_NVME_PCI=a\nX=1\nROOTFS_NVME_PCI=b\n")
    _apply(work, nvme_pci="0005:01:00.0")
    assert _env(work).count('ROOTFS_NVME_PCI="0005:01:00.0"') == 2
    assert _env(work).count("ROOTFS_NVME_PCI") == 2


def test_an_indented_pin_line_is_not_replaced_and_a_new_one_is_appended(tmp_path):
    work = _work(tmp_path, PLACEHOLDER_ENV + " ROOTFS_NVME_PCI=a\n")
    _apply(work, nvme_pci="0005:01:00.0")
    assert _env(work) == NVME_ENV + ' ROOTFS_NVME_PCI=a\nROOTFS_NVME_PCI="0005:01:00.0"\n'


@pytest.mark.deviation("env-append-newline")
def test_append_starts_a_new_line_when_the_file_has_no_trailing_newline(tmp_path):
    work = _work(tmp_path, 'BOOTDEV="p"\nROOTFS_DEVICE="p"\nEXTERNAL_ROOTFS_DRIVE=0')
    _apply(work, nvme_pci="0005:01:00.0")
    assert _env(work) == NVME_ENV.rstrip("\n") + '\nROOTFS_NVME_PCI="0005:01:00.0"\n'


# --- validation ---


@pytest.mark.parametrize(
    "bad",
    [
        "5:1:0.0",
        "0005:01:00",
        "/sys/bus/pci/devices/0005:01:00.0",
        "0005:01:00.0;reboot",
        "nvme1n1",
        "0005:01:00.8",
        "0005:01:00.0\n",
        "0005:01:00.0 ",
        "0005:1:00.0",
        "0005:01:00:0",
        "000G:01:00.0",
        "0005:01:00.١",
    ],
)
def test_malformed_override_is_refused_with_the_old_text_and_writes_no_pin(tmp_path, bad):
    work = _work(tmp_path)
    with pytest.raises(EngineError) as exc:
        _apply(work, nvme_pci=bad)
    assert str(exc.value) == EXPECTED_ERROR.format(bad=bad)
    assert "ROOTFS_NVME_PCI" not in _env(work)


def test_uppercase_hex_is_refused_like_the_lowercase_only_bash_pattern(tmp_path):
    work = _work(tmp_path)
    with pytest.raises(EngineError):
        _apply(work, nvme_pci="000A:01:00.0")


def test_malformed_carrier_value_is_refused_too(tmp_path):
    work = _work(tmp_path, carrier='CARRIER_NVME_PCI="nvme1n1"\n')
    with pytest.raises(EngineError, match="'nvme1n1' is not a PCI address"):
        _apply(work)


@pytest.mark.parametrize("fn", range(8))
def test_function_numbers_0_to_7_are_accepted(tmp_path, fn):
    work = _work(tmp_path)
    _apply(work, nvme_pci=f"0000:ff:1f.{fn}")
    assert f'ROOTFS_NVME_PCI="0000:ff:1f.{fn}"' in _env(work)


@pytest.mark.parametrize("media", [Media.EMMC, Media.SD])
def test_other_media_ignore_the_knob_even_when_malformed(tmp_path, media):
    work = _work(tmp_path)
    (work / "internal-flash-emmc.xml").write_text("<x/>")
    lines = _apply(work, nvme_pci="garbage", media=media)
    assert "ROOTFS_NVME_PCI" not in _env(work)
    assert not any("NVMe" in line for line in lines)


# --- the staged env stays readable ---


def test_the_pin_line_does_not_trip_the_plain_env_reader(tmp_path):
    work = _work(tmp_path)
    _apply(work, nvme_pci="0005:01:00.0")
    plain = read_plain_env(work / ENV_NAME)
    assert plain.get("ROOTFS_DEVICE") == "nvme0n1"
    assert plain.get("EXTERNAL_ROOTFS_DRIVE") == "1"


# --- environment plumbing ---


def _cfg(**extra):
    env = {"AVOCADO_STONE_MANIFEST": "/m", "AVOCADO_STONE_BUILD_DIR": "/b", "AVOCADO_STONE_DATA_DIR": "/d"}
    env.update(extra)
    return from_environ(env)


def test_config_reads_the_override():
    assert _cfg(AVOCADO_PROVISION_NVME_PCI="0005:01:00.0").nvme_pci == "0005:01:00.0"


def test_config_treats_an_empty_override_as_unset():
    assert _cfg(AVOCADO_PROVISION_NVME_PCI="").nvme_pci == ""
    assert _cfg().nvme_pci == ""


def test_flash_environment_keeps_the_override_for_initrd_flash(tmp_path):
    env = flash_environment(
        {"PATH": "/bin", "AVOCADO_PROVISION_NVME_PCI": "0005:01:00.0"},
        wrapper_dir=tmp_path,
        work_dir=tmp_path,
        pythonwarnings=None,
    )
    assert env["AVOCADO_PROVISION_NVME_PCI"] == "0005:01:00.0"


# --- through the engine entry point ---


def _run(tmp_path, capsys, *, profile="tegraflash-nvme", env=None, carrier=None):
    rig = make_rig(tmp_path, profile=profile, env=env, carrier=carrier)
    rc, out, err = rig.go(main, capsys)
    return rig, rc, out, err


def test_cli_override_is_announced_and_staged(tmp_path, capsys):
    rig, rc, out, _ = _run(tmp_path, capsys, env={"AVOCADO_PROVISION_NVME_PCI": "0003:01:00.0"})
    assert rc == 0
    assert "NVMe flash target: PCIe 0003:01:00.0\n" in out
    assert 'ROOTFS_NVME_PCI="0003:01:00.0"\n' in (rig.work / ENV_NAME).read_text()
    flash = rig.runner.named("initrd-flash")[0]
    assert flash.env["AVOCADO_PROVISION_NVME_PCI"] == "0003:01:00.0"


def test_cli_carrier_pin_is_announced_after_the_media_line(tmp_path, capsys):
    carrier = {"CARRIER_LABEL": "Pin Carrier", "CARRIER_NVME_PCI": '"0005:01:00.0"'}
    rig, rc, out, _ = _run(tmp_path, capsys, carrier=carrier)
    assert rc == 0
    assert out.index("Boot media target: nvme") < out.index("NVMe flash target: PCIe 0005:01:00.0")
    assert 'ROOTFS_NVME_PCI="0005:01:00.0"\n' in (rig.work / ENV_NAME).read_text()


def test_cli_malformed_override_exits_1_with_the_old_stderr_and_never_flashes(tmp_path, capsys):
    rig, rc, out, err = _run(tmp_path, capsys, env={"AVOCADO_PROVISION_NVME_PCI": "nvme1n1"})
    assert rc == 1
    assert err == "ERROR: " + EXPECTED_ERROR.format(bad="nvme1n1") + "\n"
    assert "NVMe flash target" not in out
    assert rig.runner.named("initrd-flash") == []


def test_cli_unset_leaves_the_staged_env_without_a_pin(tmp_path, capsys):
    rig, rc, out, _ = _run(tmp_path, capsys)
    assert rc == 0 and "NVMe flash target" not in out
    assert "ROOTFS_NVME_PCI" not in (rig.work / ENV_NAME).read_text()


def test_cli_non_nvme_profile_ignores_a_malformed_override(tmp_path, capsys):
    rig, rc, out, _ = _run(tmp_path, capsys, profile="tegraflash-mmc", env={"AVOCADO_PROVISION_NVME_PCI": "bogus"})
    assert rc == 0 and "NVMe flash target" not in out


def test_verify_staged_env_accepts_a_pinned_file(tmp_path):
    work = _work(tmp_path)
    _apply(work, nvme_pci="0005:01:00.0")
    (work / ENV_NAME).write_text(_env(work) + "DATAFILE=var.img\n")

    class M:
        var = "var.img"

    assert verify_staged_env(work, M(), "nvme0n1").device == "nvme0n1"
