"""The `boards` command lists the registry without touching hardware."""

import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "remote"))
from media_fixtures import load_avocado_flash, run_main_in_process, run_script  # noqa: E402

GOLDEN = pathlib.Path(__file__).resolve().parent / "golden" / "help.txt"


MARK_OLD = "### argparse before 3.13\n"
MARK_NEW = "### argparse 3.13 and later\n"


def _golden_section() -> str:
    """argparse prints `-m MACHINE, --machine MACHINE` before 3.13 and
    `-m, --machine MACHINE` from 3.13, so the golden holds both layouts."""
    text = GOLDEN.read_text()
    assert text.startswith(MARK_OLD) and text.count(MARK_NEW) == 1
    old, new = text[len(MARK_OLD):].split(MARK_NEW)
    return new if sys.version_info >= (3, 13) else old


@pytest.fixture
def no_subprocess(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError(f"subprocess started: {args!r}")

    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "call", refuse)
    monkeypatch.setattr(subprocess, "check_call", refuse)
    monkeypatch.setattr(subprocess, "check_output", refuse)


def _run_boards(monkeypatch, tmp_path):
    result = run_main_in_process(load_avocado_flash(), ["boards"], monkeypatch, tmp_path)
    return result.exit, result.stdout


def test_boards_lists_seven_lines_with_orin_nano_id(monkeypatch, tmp_path, no_subprocess):
    rc, out = _run_boards(monkeypatch, tmp_path)
    lines = out.splitlines()
    assert rc == 0
    assert len(lines) == 7
    orin = [ln for ln in lines if "0955:7523" in ln]
    assert len(orin) == 1
    assert sum(ln.rstrip().endswith("none recorded") for ln in lines) == 6


def test_boards_line_names_machine_family_and_id(monkeypatch, tmp_path, no_subprocess):
    from avocado_flash_boards import all_boards

    _rc, out = _run_boards(monkeypatch, tmp_path)
    for board, line in zip(all_boards(), out.splitlines()):
        fields = line.split()
        assert fields[0] == board.machine
        assert fields[1] == board.family
        assert " ".join(fields[2:]) == (board.rcm_id or "none recorded")


def test_boards_succeeds_with_subprocess_creation_forbidden(monkeypatch, tmp_path, no_subprocess):
    rc, _out = _run_boards(monkeypatch, tmp_path)
    assert rc == 0


def test_live_help_equals_golden(tmp_path):
    live = run_script(["--help"], tmp_path, tmp_path).stdout
    assert live == _golden_section()
    assert "boards" not in live


def test_a_bad_registry_entry_prints_a_clean_message_not_a_traceback(monkeypatch, capsys):
    import avocado_flash_boards as boards_pkg
    from avocado_flash_boards import cli

    monkeypatch.setattr(boards_pkg.tegra, "BOARDS", [boards_pkg.Board("avocado-x", "tegar")])
    boards_pkg._registry.cache_clear()
    try:
        rc = cli.main([])
    finally:
        monkeypatch.undo()
        boards_pkg._registry.cache_clear()
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "avocado-x" in captured.err and "Traceback" not in captured.err
