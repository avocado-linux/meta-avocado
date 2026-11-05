import pytest

from avocado_tegraflash import EngineError, Media
from avocado_tegraflash.cli import main


def test_prepare_only_with_unwired_stages_reports_error_and_returns_1(capsys):
    rc = main(["--prepare-only"], environ={}, euid=0)
    assert rc == 1
    assert capsys.readouterr().err == "ERROR: engine stages are not wired\n"


def test_no_arguments_never_returns_0_while_stages_unwired(capsys):
    assert main([], environ={}) != 0


@pytest.mark.parametrize("argv", [["--bogus"], ["--prepare-only", "extra"], ["-h"], ["--help"], ["--prepare-only=1"]])
def test_other_arguments_exit_2(argv, capsys):
    assert main(argv) == 2
    assert "usage:" in capsys.readouterr().err


def test_engine_error_is_exception_and_media_members():
    assert issubclass(EngineError, Exception)
    assert {m.name for m in Media} == {"NVME", "EMMC", "SD"}
