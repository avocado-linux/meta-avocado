"""archive_image must drop only the archive's own extension.

A dotted directory anywhere in the path (e.g. /home/u/.wt/x/a.fwup) must be
preserved; cutting at the first dot turns it into /home/u/.img.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

SCRIPTS = [
    "meta-avocado-nxp/stone/avocado-imx/stone-provision-img.sh",
    "meta-avocado-nxp/stone/avocado-imx/stone-provision-sd.sh",
    "meta-avocado-nxp/stone/avocado-imx/stone-provision-uuu-emmc.sh",
    "meta-avocado-raspberrypi/stone/rpi/stone-provision-img.sh",
    "meta-avocado-raspberrypi/stone/rpi/stone-provision-sd.sh",
    "meta-avocado-synaptics/stone/avocado/stone-provision-img.sh",
    "meta-avocado-synaptics/stone/avocado/stone-provision-sd.sh",
    "meta-avocado-qemu/stone/qemuarm64/stone-provision-img.sh",
]

ARCHIVE = "/home/u/.wt/x/a.fwup"


@pytest.mark.parametrize("script", SCRIPTS, ids=SCRIPTS)
def test_archive_image_keeps_dotted_directory(script, tmp_path):
    lines = [
        line
        for line in (ROOT / script).read_text().splitlines()
        if re.match(r"\s*archive_image=", line)
    ]
    assert len(lines) == 1, f"expected one archive_image line, got {lines}"
    out = tmp_path / "out.txt"
    with out.open("w") as fh:
        proc = subprocess.run(
            [
                "bash",
                "-c",
                f'archive_file="{ARCHIVE}"; {lines[0]}; printf %s "$archive_image"',
            ],
            stdout=fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            timeout=30,
            start_new_session=True,
        )
    assert proc.returncode == 0
    assert out.read_text() == "/home/u/.wt/x/a.img"
