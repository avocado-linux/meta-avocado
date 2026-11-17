"""The real provisioning shim run into the real engine entry point.

test_shim.py uses a stand-in package and the parity driver calls main()
directly, so nothing else proves the two fit together: the path the shim hands
over, the isolated interpreter flags, and the package import from the data
directory. This runs with --prepare-only, which touches no board.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from parity import runner
from parity.cases import STONE_DIR, Case

SHIM = STONE_DIR / "tegra" / "stone-provision-tegraflash.sh"
PACKAGE = STONE_DIR / "tegra" / "avocado_tegraflash"
MANIFEST = STONE_DIR / "stone-jetson-orin-nano.json"
PROFILE = "tegraflash-nvme"
TIMEOUT = 60

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")


def _run_shim(env: dict, workdir: Path) -> tuple[int, str]:
    out = workdir / "shim.out"
    with open(out, "wb") as sink:
        status = runner.run_in_own_session(
            ["/bin/bash", str(SHIM), "--prepare-only"],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=sink,
            timeout=TIMEOUT,
        )
    return status, out.read_text()


def _staged(tmp_path: Path, *, with_engine: bool):
    case = Case(id="shim-engine", manifest=MANIFEST, profile=PROFILE)
    s = runner.setup(case, tmp_path)
    engine = s.tree.data_dir / "tegraflash-engine"
    # The fixture stages the manifest's engine entry as a placeholder; the real
    # deploy puts the package directory there.
    if engine.is_file():
        engine.unlink()
    if with_engine:
        shutil.copytree(
            PACKAGE,
            engine / "avocado_tegraflash",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    return s, runner.build_env(case, s)


def test_shim_runs_the_real_engine_through_prepare_only(tmp_path):
    s, env = _staged(tmp_path, with_engine=True)
    status, output = _run_shim(env, tmp_path)
    lines = output.splitlines()
    called = {call["tool"] for call in runner.read_calls(s.log_path)}
    assert status == 0, output
    assert lines[-2].startswith("Work directory:"), output
    assert lines[-1] == "Command: ./initrd-flash --erase-nvme", output
    assert not called & {"lsusb", "boardctl"}, called


def test_shim_without_an_engine_directory_refuses_and_says_so(tmp_path):
    s, env = _staged(tmp_path, with_engine=False)
    status, output = _run_shim(env, tmp_path)
    assert status != 0
    assert "engine not found" in output
    assert str(s.tree.data_dir / "tegraflash-engine") in output
    assert json.dumps(runner.read_calls(s.log_path)) == "[]"
