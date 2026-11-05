"""Shared fixtures for the Jetson NVMe recovery-mode flash tests.

Two autouse guards keep the default suite hermetic: any socket connect
fails, and any process spawn fails unless the test carries the
``real_subprocess`` marker, so the default suite can never run sudo or a
flash tool.
"""

import dataclasses
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys

import pytest

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[2]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

REPO_ROOT = SCRIPTS_DIR.parent
REAL_TEMPLATE = REPO_ROOT / "meta-avocado-nvidia" / "stone" / "stone-jetson-orin-nano.json"
MACHINE = "avocado-jetson-orin-nano"
DIR_KEYS = ("tegraflash_bsp", "tegraflash_engine", "tegraflash_tools", "tegraflash_carrier_bsp")

_STUB_SCRIPT = """#!/bin/sh
{
  export -p
  printf 'ARGS:'
  for a in "$@"; do printf ' %s' "$a"; done
  printf '\\n'
  printf 'PWD: %s\\n' "$(pwd)"
} >> "$STUB_RECORD"
"""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_subprocess: allow this test to spawn real processes",
    )


def _refuse_socket(method):
    def guarded(self, address, *args, **kwargs):
        # pytest.fail raises a BaseException subclass, so code wrapping the
        # connect in `except Exception` / `except OSError` cannot swallow it.
        pytest.fail(
            f"network connection attempted: socket.{method}({address!r}); "
            "the default suite must use stubs",
            pytrace=False,
        )

    return guarded


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _refuse_socket("connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse_socket("connect_ex"))


def _refuse_spawn(name):
    def guarded(*args, **kwargs):
        pytest.fail(
            f"{name} called without the real_subprocess marker; the default "
            "suite must never run sudo or a flash tool",
            pytrace=False,
        )

    return guarded


@pytest.fixture(autouse=True)
def _no_subprocess(request, monkeypatch):
    if request.node.get_closest_marker("real_subprocess"):
        return
    for name in ("run", "Popen", "call", "check_output"):
        monkeypatch.setattr(subprocess, name, _refuse_spawn(f"subprocess.{name}"))
    monkeypatch.setattr(os, "system", _refuse_spawn("os.system"))


def layout_xml(sizes: dict) -> str:
    """A partition layout in the deployed external-flash.xml shape.

    A value that is not an int is written verbatim, so a test can plant a
    placeholder such as ``DATASIZE``.
    """
    parts = "".join(
        f'        <partition name="{name}" type="data">\n'
        "            <allocation_policy> sequential </allocation_policy>\n"
        f"            <size> {size} </size>\n"
        "        </partition>\n"
        for name, size in sizes.items()
    )
    return (
        '<?xml version="1.0"?>\n'
        '<partition_layout version="01.00.0000">\n'
        '    <device type="external" instance="0" sector_size="512" num_sectors="119537664" >\n'
        f"{parts}"
        "    </device>\n"
        "</partition_layout>\n"
    )


@pytest.fixture
def make_layout():
    return layout_xml


@dataclasses.dataclass(frozen=True)
class DeployTree:
    images_dir: pathlib.Path
    real_template: pathlib.Path
    template: pathlib.Path
    script: pathlib.Path
    tools_dir: pathlib.Path
    bsp_dir: pathlib.Path
    carrier_dir: pathlib.Path
    kernel_image: pathlib.Path
    machine: str = MACHINE


@pytest.fixture
def deploy_tree(tmp_path):
    images_dir = tmp_path / "deploy" / "images" / MACHINE
    images_dir.mkdir(parents=True)
    template_path = images_dir / REAL_TEMPLATE.name
    shutil.copyfile(REAL_TEMPLATE, template_path)
    images = json.loads(REAL_TEMPLATE.read_text())["storage_devices"]["rootdisk"]["images"]
    dirs = {}
    for key, name in images.items():
        if not isinstance(name, str):
            continue
        path = images_dir / name
        if key in DIR_KEYS:
            path.mkdir()
            (path / "placeholder").write_text("x\n")
            dirs[key] = path
        else:
            path.write_bytes(b"image-" + key.encode() + b"\n")
    (dirs["tegraflash_bsp"] / "external-flash.xml").write_text(
        layout_xml({"esp": 67108864, "APP": 268435456, "APP_b": 268435456})
    )
    tools = dirs["tegraflash_tools"]
    initrd = tools / "initrd-flash"
    initrd.write_text("#!/bin/sh\nexit 0\n")
    initrd.chmod(0o755)
    kernel = images_dir / "Image"
    kernel.write_bytes(b"kernel\n")
    script = images_dir / "stone-provision-tegraflash.sh"
    script.write_text(_STUB_SCRIPT)
    script.chmod(0o755)
    return DeployTree(
        images_dir=images_dir,
        real_template=REAL_TEMPLATE,
        template=template_path,
        script=script,
        tools_dir=tools,
        bsp_dir=dirs["tegraflash_bsp"],
        carrier_dir=dirs["tegraflash_carrier_bsp"],
        kernel_image=kernel,
    )
