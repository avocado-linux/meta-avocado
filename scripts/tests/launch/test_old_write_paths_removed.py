"""The old sd, ums and nvme write paths and the Jetson registry are gone; boards still lists the Jetsons."""

import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2]
SCRIPT = SCRIPTS / "avocado-flash"


def test_removed_packages_and_test_trees_do_not_exist():
    for gone in (
        "avocado_flash_tegra",
        "avocado_flash_boards",
        "tests/tegra",
        "tests/boards",
        "tests/remote/test_existing_media.py",
    ):
        assert not (SCRIPTS / gone).exists(), gone


def test_boards_verb_lists_the_seven_jetsons_from_the_launcher_package():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "boards"],
        env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert proc.returncode == 0, proc.stderr
    assert len(lines) == 7
    assert any("jetson-orin-nano" in ln and "0955:7523" in ln for ln in lines)
