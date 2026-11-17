"""Boot-device settings: .env.initrd-flash rewrites and the eMMC layout copy.

Ports tests/test-sd-device-name.sh (oracle lines 529-585) case by case.
"""

import hashlib
from pathlib import Path

import pytest

from avocado_tegraflash import EngineError, Media
from avocado_tegraflash.settings import apply_boot_device

ENV_NAME = ".env.initrd-flash"
PLACEHOLDER_ENV = 'BOOTDEV="placeholder"\nROOTFS_DEVICE="placeholder"\nEXTERNAL_ROOTFS_DRIVE=0\n'


def _work(tmp_path: Path, env: str = PLACEHOLDER_ENV) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    (work / ENV_NAME).write_text(env)
    return work


def _env(work: Path) -> str:
    return (work / ENV_NAME).read_text()


def _snapshot(work: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(work.iterdir()) if p.is_file()}


def _sd(work: Path, device: str, log=lambda _m: None) -> None:
    apply_boot_device(work, Media.SD, sd_device=device, log=log)


# --- NVMe ---


def test_nvme_sets_bootdev_rootfs_and_external_drive(tmp_path):
    work = _work(tmp_path)
    apply_boot_device(work, Media.NVME, sd_device="")
    assert _env(work) == 'BOOTDEV="nvme0n1p1"\nROOTFS_DEVICE="nvme0n1"\nEXTERNAL_ROOTFS_DRIVE=1\n'


def test_nvme_adds_no_appuuid_and_keeps_other_keys(tmp_path):
    work = _work(tmp_path, PLACEHOLDER_ENV + "OTHER=keep\n")
    apply_boot_device(work, Media.NVME, sd_device="")
    assert _env(work).endswith("OTHER=keep\n") and "APPUUID" not in _env(work)


def test_nvme_ignores_an_invalid_sd_device(tmp_path):
    work = _work(tmp_path)
    apply_boot_device(work, Media.NVME, sd_device="/dev/bogus")
    assert 'BOOTDEV="nvme0n1p1"' in _env(work)


def test_nvme_replaces_every_matching_line_like_sed(tmp_path):
    work = _work(tmp_path, 'BOOTDEV="a"\nX=1\nBOOTDEV="b"\nROOTFS_DEVICE=r\nEXTERNAL_ROOTFS_DRIVE=0\n')
    apply_boot_device(work, Media.NVME, sd_device="")
    assert _env(work).startswith('BOOTDEV="nvme0n1p1"\nX=1\nBOOTDEV="nvme0n1p1"\n')


def test_key_must_start_the_line(tmp_path):
    work = _work(tmp_path, PLACEHOLDER_ENV + ' BOOTDEV=x\nXBOOTDEV=y\n#BOOTDEV=z\n')
    apply_boot_device(work, Media.NVME, sd_device="")
    assert _env(work).endswith(' BOOTDEV=x\nXBOOTDEV=y\n#BOOTDEV=z\n')


def test_final_line_without_newline_stays_without_newline(tmp_path):
    work = _work(tmp_path, 'BOOTDEV="a"\nROOTFS_DEVICE=r\nEXTERNAL_ROOTFS_DRIVE=0')
    apply_boot_device(work, Media.NVME, sd_device="")
    assert _env(work) == 'BOOTDEV="nvme0n1p1"\nROOTFS_DEVICE="nvme0n1"\nEXTERNAL_ROOTFS_DRIVE=1'


def test_missing_env_file_raises(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    with pytest.raises(EngineError, match=ENV_NAME):
        apply_boot_device(work, Media.NVME, sd_device="")


# --- eMMC ---


def test_emmc_sets_settings_and_copies_internal_layout(tmp_path):
    work = _work(tmp_path)
    (work / "internal-flash-emmc.xml").write_text("<emmc/>")
    (work / "external-flash.xml.in").write_text("<old/>")
    apply_boot_device(work, Media.EMMC, sd_device="")
    assert _env(work) == 'BOOTDEV="mmcblk0p1"\nROOTFS_DEVICE="mmcblk0"\nEXTERNAL_ROOTFS_DRIVE=1\n'
    assert (work / "external-flash.xml.in").read_text() == "<emmc/>"


def test_emmc_creates_external_layout_when_absent(tmp_path):
    work = _work(tmp_path)
    (work / "internal-flash-emmc.xml").write_text("<emmc/>")
    apply_boot_device(work, Media.EMMC, sd_device="")
    assert (work / "external-flash.xml.in").read_text() == "<emmc/>"


def test_emmc_without_internal_layout_raises(tmp_path):
    work = _work(tmp_path)
    with pytest.raises(EngineError, match="internal-flash-emmc.xml"):
        apply_boot_device(work, Media.EMMC, sd_device="")


def test_emmc_leaves_flash_xml_in_untouched(tmp_path):
    work = _work(tmp_path)
    (work / "internal-flash-emmc.xml").write_text("<emmc/>")
    (work / "flash.xml.in").write_text("<spi/>")
    apply_boot_device(work, Media.EMMC, sd_device="")
    assert (work / "flash.xml.in").read_text() == "<spi/>"


def test_emmc_logs_the_layout_swap(tmp_path):
    work = _work(tmp_path)
    (work / "internal-flash-emmc.xml").write_text("<emmc/>")
    lines: list[str] = []
    apply_boot_device(work, Media.EMMC, sd_device="", log=lines.append)
    assert lines == [
        "Using eMMC flash layout (internal-flash-emmc.xml -> external-flash.xml.in)"
    ]


# --- SD (old test-sd-device-name.sh cases) ---


@pytest.mark.parametrize("device", ["mmcblk0", "mmcblk1", "mmcblk3", "mmcblk12"])
def test_sd_declared_device_reaches_bootdev_and_rootfs(tmp_path, device):
    # old case 1 (mmcblk0, mmcblk1 reach BOOTDEV/ROOTFS_DEVICE) and old case 2
    # (an unusual value, mmcblk3, so no hardcode passes)
    work = _work(tmp_path)
    _sd(work, device)
    assert _env(work) == (
        f'BOOTDEV="{device}p1"\nROOTFS_DEVICE="{device}"\nEXTERNAL_ROOTFS_DRIVE=1\n'
    )


def test_sd_sets_external_rootfs_drive(tmp_path):
    # old case 1b: EXTERNAL_ROOTFS_DRIVE is set for SD boot
    work = _work(tmp_path)
    _sd(work, "mmcblk0")
    assert "EXTERNAL_ROOTFS_DRIVE=1\n" in _env(work)


def test_sd_logs_the_device(tmp_path):
    work = _work(tmp_path)
    lines: list[str] = []
    _sd(work, "mmcblk0", log=lines.append)
    assert lines == ["SD card device: mmcblk0"]


def test_sd_empty_device_raises_and_changes_nothing(tmp_path):
    # old case 3: nothing declared, the branch fails and writes nothing
    work = _work(tmp_path)
    before = _snapshot(work)
    with pytest.raises(EngineError):
        _sd(work, "")
    assert _snapshot(work) == before


def test_sd_empty_device_names_both_sources(tmp_path):
    # old case 3b: the refusal names the manifest key and the environment variable
    work = _work(tmp_path)
    with pytest.raises(EngineError) as exc:
        _sd(work, "")
    assert "sd_device" in str(exc.value)
    assert "AVOCADO_PROVISION_SD_DEVICE" in str(exc.value)


@pytest.mark.parametrize(
    "bad",
    [
        "/dev/mmcblk1",  # old case 4
        "mmcblk1p1",  # old case 4 (partition)
        "mmcblk1&",  # old case 4 (sed metacharacter)
        "mmcblk",
        "mmcblk1\n",
        "MMCBLK1",
        " mmcblk1",
        "mmcblk1 ",
        "mmcblk١",  # Arabic-indic digit one
        "mmcblk1\\1",
        "mmcblk1/",
        "nvme0n1",
    ],
)
def test_sd_invalid_device_raises_and_leaves_files_byte_identical(tmp_path, bad):
    work = _work(tmp_path)
    (work / "other.txt").write_bytes(b"\x00keep")
    before = _snapshot(work)
    with pytest.raises(EngineError, match="mmcblkN"):
        _sd(work, bad)
    assert _snapshot(work) == before


def test_sd_invalid_device_is_checked_even_when_env_file_is_missing(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    with pytest.raises(EngineError, match="mmcblkN"):
        _sd(work, "/dev/mmcblk1")


def test_sd_device_with_regex_template_chars_never_reaches_file(tmp_path):
    work = _work(tmp_path)
    with pytest.raises(EngineError):
        _sd(work, "mmcblk1\\g<0>")
    assert _env(work) == PLACEHOLDER_ENV


# --- mutation proofs: the falsifiers must fail on a broken copy ---


def test_mutant_skipping_sd_validation_is_caught(tmp_path, mutant):
    mod = mutant("settings.py", "if not _SD_DEVICE.fullmatch(sd_device):", "if False:")
    work = _work(tmp_path)
    mod.apply_boot_device(work, mod.Media.SD, sd_device="/dev/mmcblk1", log=lambda _m: None)
    assert 'BOOTDEV="/dev/mmcblk1p1"' in _env(work)


def test_mutant_prefix_match_lets_a_partition_name_through(tmp_path, mutant):
    mod = mutant("settings.py", "_SD_DEVICE.fullmatch(sd_device)", "_SD_DEVICE.match(sd_device)")
    work = _work(tmp_path)
    mod.apply_boot_device(work, mod.Media.SD, sd_device="mmcblk1p1", log=lambda _m: None)
    assert 'ROOTFS_DEVICE="mmcblk1p1"' in _env(work)


def test_mutant_emmc_without_layout_check_proceeds(tmp_path, mutant):
    mod = mutant("settings.py", "if not layout.is_file():", "if False:")
    work = _work(tmp_path)
    # The mutant package has its own EngineError class, so match on the message.
    with pytest.raises(Exception, match="cannot copy"):
        mod.apply_boot_device(work, mod.Media.EMMC, sd_device="")


# --- the staged source behind a symlink is never modified ---


def test_env_file_symlink_is_replaced_not_followed(tmp_path):
    outside = tmp_path / "outside.env"
    outside.write_text(PLACEHOLDER_ENV)
    before = hashlib.sha256(outside.read_bytes()).hexdigest()
    work = tmp_path / "work"
    work.mkdir()
    (work / ENV_NAME).symlink_to(outside)
    apply_boot_device(work, Media.NVME, sd_device="")
    target = work / ENV_NAME
    assert (
        hashlib.sha256(outside.read_bytes()).hexdigest() == before,
        target.is_symlink(),
        target.read_text(),
    ) == (True, False, 'BOOTDEV="nvme0n1p1"\nROOTFS_DEVICE="nvme0n1"\nEXTERNAL_ROOTFS_DRIVE=1\n')


# --- a requested key absent from the env file ---


@pytest.mark.deviation("env-key-missing-refused")
@pytest.mark.parametrize("key", ["BOOTDEV", "ROOTFS_DEVICE", "EXTERNAL_ROOTFS_DRIVE"])
def test_missing_key_is_refused_naming_key_and_file_and_changes_nothing(tmp_path, key):
    env = "".join(line for line in PLACEHOLDER_ENV.splitlines(keepends=True) if not line.startswith(key))
    work = _work(tmp_path, env)
    with pytest.raises(EngineError) as info:
        apply_boot_device(work, Media.NVME, sd_device="")
    assert key in str(info.value) and ENV_NAME in str(info.value)
    assert _env(work) == env


def test_non_utf8_byte_in_the_env_file_is_preserved(tmp_path):
    work = _work(tmp_path)
    (work / ENV_NAME).write_bytes(b"NOTE=caf\xe9\n" + PLACEHOLDER_ENV.encode())
    apply_boot_device(work, Media.NVME, sd_device="")
    assert (work / ENV_NAME).read_bytes().startswith(b"NOTE=caf\xe9\n")


def test_carriage_returns_survive_on_untouched_lines(tmp_path):
    work = _work(tmp_path)
    (work / ENV_NAME).write_bytes(b"NOTE=a\r\n" + PLACEHOLDER_ENV.encode())
    apply_boot_device(work, Media.NVME, sd_device="")
    assert (work / ENV_NAME).read_bytes().startswith(b"NOTE=a\r\n")


@pytest.mark.deviation("symlink-destination-replaced")
def test_emmc_layout_copy_replaces_a_destination_link(tmp_path):
    work = _work(tmp_path)
    (work / "internal-flash-emmc.xml").write_text("layout")
    outside = tmp_path / "outside"
    outside.write_text("untouched")
    (work / "external-flash.xml.in").symlink_to(outside)
    apply_boot_device(work, Media.EMMC, sd_device="", log=lambda _m: None)
    assert outside.read_text() == "untouched" and (work / "external-flash.xml.in").read_text() == "layout"
