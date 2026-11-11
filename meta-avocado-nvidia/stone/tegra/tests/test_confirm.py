"""Tests for avocado_tegraflash.confirm and the AVOCADO_PROVISION_FORCE tri-state."""

import sys

import pytest

from avocado_tegraflash import EngineError, Media
from avocado_tegraflash.confirm import confirm_device, stdin_is_tty
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
