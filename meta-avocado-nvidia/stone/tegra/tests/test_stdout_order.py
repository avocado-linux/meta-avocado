import io
import subprocess
import sys
from pathlib import Path

from avocado_tegraflash import cli

PKG_PARENT = Path(cli.__file__).resolve().parent.parent


def test_main_makes_piped_stdout_line_buffered(monkeypatch):
    raw = io.BytesIO()
    piped = io.TextIOWrapper(raw, line_buffering=False, write_through=False)
    monkeypatch.setattr(sys, "stdout", piped)
    assert piped.line_buffering is False

    cli.main(["--no-such-option"])

    assert piped.line_buffering is True


def test_engine_lines_precede_a_child_process_when_piped(tmp_path):
    # The engine's print and a child's write share one pipe: the engine's line must land first.
    script = tmp_path / "order.py"
    script.write_text(
        "import subprocess, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from avocado_tegraflash import cli\n"
        "cli.main(['--no-such-option'])\n"
        "print('engine line')\n"
        "subprocess.run(['echo', 'child line'])\n"
    )
    out = subprocess.run(
        [sys.executable, "-I", "-B", str(script), str(PKG_PARENT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    ).stdout
    assert out.splitlines() == ["engine line", "child line"]
