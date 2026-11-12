"""Tests for avocado_tegraflash.confirm and the AVOCADO_PROVISION_FORCE tri-state."""

import sys
from pathlib import Path

import pytest

from avocado_tegraflash import EngineError, Media
from avocado_tegraflash.confirm import confirm_device, decide_confirmation, stdin_is_tty
from avocado_tegraflash.env import from_environ
from avocado_tegraflash.usb import UsbDevice

BOARD = UsbDevice("001", "007", "0955", "7523", "APX")


def run(force, tty, answer=None):
    prompts, logs = [], []

    def read(prompt):
        prompts.append(prompt)
        if answer is None:
            raise AssertionError("read must not be called")
        return answer

    confirm_device(BOARD, Media.NVME, force=force, isatty=lambda: tty, read=read, log=logs.append)
    return prompts, logs


def test_force_true_skips_silently_without_reading():
    assert run(True, tty=True) == ([], [])
    assert run(True, tty=False) == ([], [])


def test_false_on_terminal_prompts_and_accepts_retype():
    prompts, logs = run(False, True, "001:007")
    assert len(prompts) == 1 and logs == []
    assert "nvme" in prompts[0] and "0955:7523" in prompts[0] and "ERASE" in prompts[0]
    assert "001:007" in prompts[0]


def test_false_without_terminal_refuses():
    with pytest.raises(EngineError, match="no terminal"):
        run(False, False)


def test_none_on_terminal_prompts():
    prompts, _ = run(None, True, "001:007")
    assert len(prompts) == 1


def test_none_without_terminal_logs_skip_and_proceeds():
    prompts, logs = run(None, False)
    assert prompts == [] and len(logs) == 1 and "no terminal" in logs[0]


@pytest.mark.parametrize("force", [False, None])
def test_wrong_retype_raises_naming_both(force):
    with pytest.raises(EngineError) as exc:
        run(force, True, "001:008")
    assert "001:008" in str(exc.value) and "001:007" in str(exc.value)


def test_empty_retype_raises():
    with pytest.raises(EngineError):
        run(None, True, "")


def test_surrounding_whitespace_on_correct_retype_is_tolerated():
    run(None, True, "  001:007\n")


def test_whitespace_inside_does_not_match():
    with pytest.raises(EngineError):
        run(None, True, "001: 007")


@pytest.mark.parametrize("exc,message", [(EOFError, "stdin closed"), (KeyboardInterrupt, "interrupted")])
def test_eof_and_interrupt_at_the_prompt_refuse_with_an_engine_error(exc, message):
    def read(_prompt):
        raise exc

    with pytest.raises(EngineError, match=message):
        confirm_device(BOARD, Media.NVME, force=None, isatty=lambda: True, read=read)


def test_stdin_is_tty_is_false_when_stdin_is_absent(monkeypatch):
    monkeypatch.setattr(sys, "stdin", None)
    assert stdin_is_tty() is False


def test_stdin_is_tty_is_false_when_stdin_is_closed(monkeypatch):
    class Closed:
        def isatty(self):
            raise ValueError("I/O operation on closed file")

    monkeypatch.setattr(sys, "stdin", Closed())
    assert stdin_is_tty() is False


def test_stdin_is_tty_reports_the_real_answer(monkeypatch):
    class Tty:
        def __init__(self, answer):
            self.answer = answer

        def isatty(self):
            return self.answer

    monkeypatch.setattr(sys, "stdin", Tty(True))
    assert stdin_is_tty() is True
    monkeypatch.setattr(sys, "stdin", Tty(False))
    assert stdin_is_tty() is False


def test_force_true_never_looks_at_stdin(monkeypatch):
    monkeypatch.setattr(sys, "stdin", None)
    confirm_device(BOARD, Media.NVME, force=True, isatty=stdin_is_tty, read=lambda _p: pytest.fail("read called"))


def _force(value=None):
    environ = {
        "AVOCADO_STONE_MANIFEST": "/m",
        "AVOCADO_STONE_BUILD_DIR": "/b",
        "AVOCADO_STONE_DATA_DIR": "/d",
    }
    if value is not None:
        environ["AVOCADO_PROVISION_FORCE"] = value
    return from_environ(environ).force


@pytest.mark.parametrize("value,expected", [(None, None), ("", None), ("1", True), ("0", False)])
def test_force_parsing(value, expected):
    assert _force(value) is expected


@pytest.mark.parametrize("value", ["yes", " 1", "true", "2"])
def test_force_rejects_other_values(value):
    with pytest.raises(EngineError, match="AVOCADO_PROVISION_FORCE"):
        _force(value)


def _prompt(media, flags):
    prompts = []
    confirm_device(
        BOARD, media, flags=flags, force=None, isatty=lambda: True, read=lambda p: prompts.append(p) or "001:007"
    )
    return prompts[0]


def test_sd_profile_with_erase_nvme_names_both_media():
    prompt = _prompt(Media.SD, ["--erase-nvme"])
    assert "sd" in prompt and "nvme" in prompt


def test_erase_emmc_flag_names_emmc():
    prompt = _prompt(Media.SD, ["--erase-emmc"])
    assert "sd" in prompt and "emmc" in prompt


def test_sd_profile_without_flags_does_not_name_nvme_or_emmc():
    prompt = _prompt(Media.SD, [])
    assert "nvme" not in prompt and "emmc" not in prompt


def test_prompt_names_qspi_and_uefi_variables():
    prompt = _prompt(Media.SD, [])
    assert "QSPI" in prompt and "UEFI" in prompt


def _prompt_for(media, flags=(), device=""):
    prompts = []
    confirm_device(
        BOARD,
        media,
        flags=flags,
        device=device,
        force=None,
        isatty=lambda: True,
        read=lambda p: prompts.append(p) or "001:007",
    )
    return prompts[0]


def test_prompt_names_the_device_node_next_to_the_medium():
    assert _prompt_for(Media.NVME, device="nvme0n1").startswith("About to ERASE nvme (nvme0n1) on the board")


def test_prompt_without_a_device_has_no_empty_parentheses():
    assert "()" not in _prompt_for(Media.NVME)


@pytest.mark.parametrize("device", ["", "x0"])
@pytest.mark.parametrize(
    "media,flag,name",
    [(Media.NVME, "--erase-nvme", "nvme"), (Media.EMMC, "--erase-emmc", "emmc")],
)
def test_a_flag_naming_the_profile_medium_does_not_list_it_twice(media, flag, name, device):
    first_line = _prompt_for(media, [flag], device).splitlines()[0]
    assert first_line.count(name) == 1, first_line


def test_flag_added_media_follow_the_profile_medium_once_each():
    first_line = _prompt_for(Media.SD, ["--erase-nvme", "--erase-emmc", "--erase-nvme"], "mmcblk1").splitlines()[0]
    assert "ERASE sd (mmcblk1), nvme, emmc on the board" in first_line


def _prompt_erasing_mmc(media, flags=(), device=""):
    prompts = []
    confirm_device(
        BOARD,
        media,
        flags=flags,
        device=device,
        erases_mmc=True,
        force=None,
        isatty=lambda: True,
        read=lambda p: prompts.append(p) or "001:007",
    )
    return prompts[0].splitlines()[0]


def test_an_env_the_flash_erases_emmc_for_names_emmc_though_no_flag_added_it():
    assert "ERASE nvme (nvme0n1), emmc on the board" in _prompt_erasing_mmc(Media.NVME, device="nvme0n1")


def test_emmc_implied_by_the_env_and_named_by_a_flag_is_listed_once():
    first_line = _prompt_erasing_mmc(Media.NVME, ["--erase-emmc"], "nvme0n1")
    assert first_line.count("emmc") == 1, first_line


def test_emmc_implied_by_the_env_is_not_listed_twice_for_the_emmc_profile():
    first_line = _prompt_erasing_mmc(Media.EMMC, device="mmcblk0")
    assert first_line.count("emmc") == 1, first_line


def test_without_the_implied_erase_the_prompt_does_not_name_emmc():
    assert "emmc" not in _prompt_for(Media.NVME, device="nvme0n1").splitlines()[0]


VECTORS = Path(__file__).resolve().parents[4] / "meta-avocado-distro" / "stone" / "tests" / "confirm-vectors.tsv"


def _vector_rows():
    lines = [ln for ln in VECTORS.read_text().splitlines() if ln and not ln.startswith("#")]
    header, *rows = [ln.split("\t") for ln in lines]
    assert header == ["force", "terminal", "dry_run", "outcome"]
    return rows


def test_vectors_dry_run_rows_exist_and_are_not_applicable_to_the_engine():
    # The engine has no dry-run mode; those rows belong to the shell library test only.
    dry = [r for r in _vector_rows() if r[2] == "yes"]
    assert len(dry) == 9


def test_engine_agrees_with_every_non_dry_run_vector_row():
    checked = 0
    for force, terminal, dry_run, outcome in _vector_rows():
        if dry_run == "yes":
            continue
        raw = {"<unset>": None, "<empty>": ""}.get(force, force)
        want = "skip" if outcome == "proceed" else outcome
        try:
            got = decide_confirmation(raw, terminal == "yes")
        except EngineError as exc:
            assert "AVOCADO_PROVISION_FORCE" in str(exc) and repr(force) in str(exc)
            got = "refuse"
        assert got == want, f"row force={force} terminal={terminal}: engine {got}, vectors {want}"
        checked += 1
    assert checked == 10
