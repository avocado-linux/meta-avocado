"""The build-time boot overlay check: the same stage as provisioning, run on scratch copies."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE_PARENT = Path(__file__).resolve().parent.parent

STOCK = "stock.dtb"
DYNAMIC = "tegra234-p3737-0000+p3701-0000-dynamic.dtbo"
CARVEOUTS = "tegra234-carveouts.dtbo"
OPTEE = "tegra-optee.dtbo"
CAM1 = "tegra234-p3737-camera-imx219-overlay.dtbo"
PLUGINS = [CARVEOUTS, DYNAMIC, CAM1, OPTEE]

BASE_DTS = """/dts-v1/;
/ {
    compatible = "test,board";
    cam { channels = <4>; };
    ext_a: ext-a { };
};
"""
CARRIER_TREE_DTS = BASE_DTS.replace("channels = <4>;", "channels = <2>;")
DYNAMIC_DTS = """/dts-v1/;
/plugin/;
/ {
    fragment@0 {
        target-path = "/cam";
        __overlay__ { channels = <4>; };
    };
    fragment-camera0 {
        target-path = "/";
        __overlay__ {
            cam0: cam0-node { link = <&ext_a>; };
        };
    };
};
"""
# A kept fragment holds the phandle of a node inside a removed camera fragment.
DANGLING_DTS = DYNAMIC_DTS.replace("channels = <4>;", "channels = <4>;\n            self = <&cam0>;")
NOOP_DTS = """/dts-v1/;
/plugin/;
/ {
    fragment@0 {
        target-path = "/";
        __overlay__ { marker = <1>; };
    };
};
"""


@pytest.fixture(autouse=True)
def _require_dtc():
    for tool in ("dtc", "fdtput", "fdtoverlay"):
        if shutil.which(tool) is None:
            pytest.fail(f"{tool} not found on PATH: install the device-tree-compiler package")


def dtb(tmp_path, dest, text):
    src = tmp_path / "dts-src" / (dest.name + ".dts")
    src.parent.mkdir(exist_ok=True)
    src.write_text(text)
    subprocess.run(["dtc", "-q", "-I", "dts", "-O", "dtb", "-@", "-o", str(dest), str(src)], check=True)


def make_bsp(tmp_path, root, *, flashvars=None, dynamic=DYNAMIC_DTS):
    root.mkdir(parents=True)
    plugins = ",".join(PLUGINS)
    (root / "flashvars").write_text(
        flashvars if flashvars is not None else f'BOOTCONTROL_OVERLAYS=""\nPLUGIN_MANAGER_OVERLAYS="{plugins}"\nOVERLAY_DTB_FILE=""\n'
    )
    (root / ".env.initrd-flash").write_text(f'DTBFILE="{STOCK}"\n')
    dtb(tmp_path, root / STOCK, BASE_DTS)
    dtb(tmp_path, root / DYNAMIC, dynamic)
    for name in (CARVEOUTS, OPTEE, CAM1):
        dtb(tmp_path, root / name, NOOP_DTS)
    return root


def make_carrier(tmp_path, root, env, *, tree=True):
    """A Shape A slot: it ships the BSP's own tree name with the integrator's values."""
    root.mkdir(parents=True)
    (root / "carrier.env").write_text(env)
    if tree:
        dtb(tmp_path, root / STOCK, CARRIER_TREE_DTS)
    return root


def write_manifest(path, bsp="/bsp", carrier="/carrier"):
    images = {"tegraflash_bsp": bsp}
    if carrier:
        images["tegraflash_carrier_bsp"] = carrier
    path.write_text(json.dumps({"storage_devices": {"rootdisk": {"images": images, "tegraflash": {}}}}))
    return path


def run(input_dir, manifest, *extra, env=None):
    full_env = {**os.environ, "PYTHONPATH": str(PACKAGE_PARENT), **(env or {})}
    return subprocess.run(
        [sys.executable, "-B", "-m", "avocado_tegraflash.buildcheck", "--input-dir", str(input_dir),
         "--manifest", str(manifest), *extra],
        capture_output=True,
        text=True,
        env=full_env,
        cwd=str(input_dir),
        stdin=subprocess.DEVNULL,
    )


def fingerprint(*roots):
    seen = {}
    for root in roots:
        for path in sorted(Path(root).rglob("*")):
            key = str(path)
            seen[key] = "dir" if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
    return seen


@pytest.fixture
def rig(tmp_path):
    inp = tmp_path / "input"
    make_bsp(tmp_path, inp / "bsp")
    make_carrier(tmp_path, inp / "carrier", f'CARRIER_ENV_DTBFILE="{STOCK}"\n')
    return inp, write_manifest(tmp_path / "manifest.json")


def test_carrier_flashvars_rewrite_is_reflected_in_the_printed_lists(tmp_path, rig):
    inp, manifest = rig
    (inp / "carrier" / "carrier.env").write_text(f'CARRIER_FV_PLUGIN_MANAGER_OVERLAYS="{CARVEOUTS},{OPTEE}"\n')
    result = run(inp, manifest)
    assert result.returncode == 0, result.stderr
    assert f"  PLUGIN_MANAGER_OVERLAYS: {CARVEOUTS},{OPTEE}\n" in result.stdout
    assert CAM1 not in result.stdout


def test_include_path_slot_wins_over_the_input_dir(tmp_path, rig):
    inp, manifest = rig
    (inp / "carrier" / "carrier.env").write_text(f'CARRIER_FV_PLUGIN_MANAGER_OVERLAYS="{OPTEE}"\n')
    inc = tmp_path / "inc"
    make_carrier(tmp_path, inc / "carrier", f'CARRIER_FV_PLUGIN_MANAGER_OVERLAYS="{CARVEOUTS}"\n')
    result = run(inp, manifest, "--include-paths", f"{tmp_path / 'empty'}:{inc}")
    assert result.returncode == 0, result.stderr
    assert f"  PLUGIN_MANAGER_OVERLAYS: {CARVEOUTS}\n" in result.stdout
    assert f"  PLUGIN_MANAGER_OVERLAYS: {OPTEE}\n" not in result.stdout


def test_first_include_path_entry_wins_over_a_later_one(tmp_path, rig):
    inp, manifest = rig
    first, second = tmp_path / "first", tmp_path / "second"
    make_carrier(tmp_path, first / "carrier", f'CARRIER_FV_PLUGIN_MANAGER_OVERLAYS="{OPTEE}"\n')
    make_carrier(tmp_path, second / "carrier", f'CARRIER_FV_PLUGIN_MANAGER_OVERLAYS="{CARVEOUTS}"\n')
    result = run(inp, manifest, "--include-paths", f"{first}:{second}")
    assert f"  PLUGIN_MANAGER_OVERLAYS: {OPTEE}\n" in result.stdout


def test_sdk_stone_dir_is_the_last_resort(tmp_path):
    inp = tmp_path / "input"
    inp.mkdir()
    sdk = tmp_path / "sdk"
    make_bsp(tmp_path, sdk / "bsp")
    make_carrier(tmp_path, sdk / "carrier", f'CARRIER_ENV_DTBFILE="{STOCK}"\n')
    result = run(inp, write_manifest(tmp_path / "m.json"), "--sdk-stone-dir", str(sdk))
    assert result.returncode == 0, result.stderr
    assert "devkit camera fragments: removed fragment-camera0" in result.stdout


def test_shape_a_camera_reset_is_warned_and_the_strip_is_reported(rig):
    inp, manifest = rig
    result = run(inp, manifest)
    assert result.returncode == 0, result.stderr
    assert "devkit camera fragments: removed fragment-camera0 from " + DYNAMIC in result.stdout
    assert f"dropped {CAM1} from PLUGIN_MANAGER_OVERLAYS" in result.stdout
    assert "WARNING: integrator-set property channels of /cam changed by " + DYNAMIC in result.stdout
    assert "Boot overlays at flash:" in result.stdout
    assert "not visible at build time; it is checked at provision." in result.stdout


def test_unreadable_assignment_exits_1_naming_the_line(tmp_path):
    inp = tmp_path / "input"
    make_bsp(tmp_path, inp / "bsp", flashvars='PLUGIN_MANAGER_OVERLAYS="$EXTRA"\n')
    make_carrier(tmp_path, inp / "carrier", f'CARRIER_ENV_DTBFILE="{STOCK}"\n')
    result = run(inp, write_manifest(tmp_path / "m.json"))
    assert result.returncode == 1
    assert "PLUGIN_MANAGER_OVERLAYS" in result.stderr
    assert "line 1" in result.stderr


def test_modified_overlay_that_keeps_a_dangling_reference_exits_1(tmp_path):
    inp = tmp_path / "input"
    make_bsp(tmp_path, inp / "bsp", dynamic=DANGLING_DTS)
    make_carrier(tmp_path, inp / "carrier", f'CARRIER_ENV_DTBFILE="{STOCK}"\n')
    result = run(inp, write_manifest(tmp_path / "m.json"))
    assert result.returncode == 1
    assert "fragment-camera0" in result.stderr


def test_unsafe_carrier_value_exits_1_as_provisioning_would(tmp_path, rig):
    inp, manifest = rig
    (inp / "carrier" / "carrier.env").write_text('CARRIER_FV_PLUGIN_MANAGER_OVERLAYS="$(id)"\n')
    result = run(inp, manifest)
    assert result.returncode == 1
    assert "CARRIER_FV_PLUGIN_MANAGER_OVERLAYS" in result.stderr


def test_inputs_are_byte_identical_and_nothing_is_added(tmp_path, rig):
    inp, manifest = rig
    inc = tmp_path / "inc"
    make_carrier(tmp_path, inc / "carrier", f'CARRIER_ENV_DTBFILE="{STOCK}"\n')
    sdk = tmp_path / "sdk"
    sdk.mkdir()
    before = fingerprint(inp, inc, sdk)
    result = run(inp, manifest, "--include-paths", str(inc), "--sdk-stone-dir", str(sdk))
    assert result.returncode == 0, result.stderr
    assert "removed fragment-camera0" in result.stdout
    assert fingerprint(inp, inc, sdk) == before


def test_missing_fdtoverlay_warns_and_exits_0(rig):
    inp, manifest = rig
    result = run(inp, manifest, env={"PATH": ""})
    assert result.returncode == 0, result.stderr
    assert "WARNING" in result.stdout
    assert "fdtoverlay" in result.stdout


def test_missing_carrier_slot_warns_and_exits_0(tmp_path):
    inp = tmp_path / "input"
    make_bsp(tmp_path, inp / "bsp")
    result = run(inp, write_manifest(tmp_path / "m.json"))
    assert result.returncode == 0, result.stderr
    assert "WARNING" in result.stdout
    assert "carrier" in result.stdout


def test_no_carrier_in_the_manifest_runs_the_stage_without_one(tmp_path):
    inp = tmp_path / "input"
    make_bsp(tmp_path, inp / "bsp")
    result = run(inp, write_manifest(tmp_path / "m.json", carrier=""))
    assert result.returncode == 0, result.stderr
    assert "no carrier device tree in use; left unchanged" in result.stdout
