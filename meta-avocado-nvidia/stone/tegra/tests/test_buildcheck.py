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
OTA = "kernel-dtb-ota.dtb"
KNOWN_SIZE = 786432
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


def layout_xml(size):
    return (
        '<partition_layout version="01.00.0000">\n'
        '  <device type="external" instance="0">\n'
        '    <partition name="A_kernel" type="kernel"><size> 134217728 </size></partition>\n'
        f'    <partition name="A_kernel-dtb" type="kernel_dtb"><size> {size} </size></partition>\n'
        "  </device>\n</partition_layout>\n"
    )


def make_bsp(tmp_path, root, *, flashvars=None, dynamic=DYNAMIC_DTS, external=KNOWN_SIZE, emmc=KNOWN_SIZE):
    root.mkdir(parents=True)
    (root / "external-flash.xml.in").write_text(layout_xml(external))
    (root / "internal-flash-emmc.xml").write_text(layout_xml(emmc))
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


def write_manifest(path, bsp="/bsp", carrier="/carrier", ota=False):
    images = {"tegraflash_bsp": bsp}
    if carrier:
        images["tegraflash_carrier_bsp"] = carrier
    if ota:
        images["kernel_dtb_ota"] = OTA
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
    inp, _ = rig
    manifest = write_manifest(tmp_path / "m-ota.json", ota=True)
    inc = tmp_path / "inc"
    make_carrier(tmp_path, inc / "carrier", f'CARRIER_ENV_DTBFILE="{STOCK}"\n')
    sdk = tmp_path / "sdk"
    sdk.mkdir()
    before = fingerprint(inp, inc, sdk)
    result = run(inp, manifest, "--include-paths", str(inc), "--sdk-stone-dir", str(sdk))
    assert result.returncode == 0, result.stderr
    assert "removed fragment-camera0" in result.stdout
    after = fingerprint(inp, inc, sdk)
    published = after.pop(str(inp / OTA))
    assert published
    assert after == before


def test_no_published_tree_without_the_manifest_declaring_it(tmp_path, rig):
    inp, manifest = rig
    result = run(inp, manifest)
    assert result.returncode == 0, result.stderr
    assert not (inp / OTA).exists()
    assert "kernel device tree" not in result.stdout


def publish(inp, tmp_path, **kw):
    return run(inp, write_manifest(tmp_path / "m-ota.json", ota=True, **kw))


def test_shape_a_published_tree_is_the_carrier_tree(tmp_path, rig):
    inp, _ = rig
    result = publish(inp, tmp_path)
    assert result.returncode == 0, result.stderr
    assert (inp / OTA).read_bytes() == (inp / "carrier" / STOCK).read_bytes()
    assert (inp / OTA).read_bytes() != (inp / "bsp" / STOCK).read_bytes()


def test_shape_b_published_tree_is_the_redirect_target(tmp_path):
    inp = tmp_path / "input"
    make_bsp(tmp_path, inp / "bsp")
    make_carrier(tmp_path, inp / "carrier", 'CARRIER_ENV_DTBFILE="custom.dtb"\n', tree=False)
    dtb(tmp_path, inp / "carrier" / "custom.dtb", CARRIER_TREE_DTS.replace("test,board", "test,custom"))
    result = publish(inp, tmp_path)
    assert result.returncode == 0, result.stderr
    assert (inp / OTA).read_bytes() == (inp / "carrier" / "custom.dtb").read_bytes()


def test_no_carrier_published_tree_is_the_stock_tree(tmp_path):
    inp = tmp_path / "input"
    make_bsp(tmp_path, inp / "bsp")
    result = publish(inp, tmp_path, carrier="")
    assert result.returncode == 0, result.stderr
    assert (inp / OTA).read_bytes() == (inp / "bsp" / STOCK).read_bytes()


def test_a_previous_copy_is_replaced_and_no_temp_file_is_left(tmp_path, rig):
    inp, _ = rig
    (inp / OTA).write_bytes(b"old")
    assert publish(inp, tmp_path).returncode == 0
    assert (inp / OTA).read_bytes() == (inp / "carrier" / STOCK).read_bytes()
    assert sorted(p.name for p in inp.iterdir()) == sorted(["bsp", "carrier", OTA])


def test_published_tree_never_lands_under_the_base_dtb_name(tmp_path, rig):
    inp, _ = rig
    before = (inp / "bsp" / STOCK).read_bytes()
    publish(inp, tmp_path)
    assert (inp / "bsp" / STOCK).read_bytes() == before
    assert not (inp / STOCK).exists()


def test_the_note_says_the_update_carries_the_kernel_tree_only(tmp_path, rig):
    inp, _ = rig
    result = publish(inp, tmp_path)
    notes = [line for line in result.stdout.splitlines() if "OS update" in line]
    assert len(notes) == 1
    assert "replaces the kernel device tree only" in notes[0]
    assert "boot overlay lists" in notes[0]
    assert "reflash" in notes[0]
    assert "CARRIER_FV" in notes[0]


def test_oversized_tree_exits_1_naming_both_sizes_and_publishes_nothing(tmp_path):
    inp = tmp_path / "input"
    make_bsp(tmp_path, inp / "bsp")
    make_carrier(tmp_path, inp / "carrier", f'CARRIER_ENV_DTBFILE="{STOCK}"\n')
    size = (inp / "carrier" / STOCK).stat().st_size
    for layout in ("external-flash.xml.in", "internal-flash-emmc.xml"):
        (inp / "bsp" / layout).write_text(layout_xml(size - 1))
    result = publish(inp, tmp_path)
    assert result.returncode == 1
    assert str(size) in result.stderr
    assert str(size - 1) in result.stderr
    assert STOCK in result.stderr
    assert not (inp / OTA).exists()


def test_the_size_limit_is_read_from_the_layout_not_hardcoded(tmp_path):
    inp = tmp_path / "input"
    make_bsp(tmp_path, inp / "bsp", external=64, emmc=64)
    result = publish(inp, tmp_path, carrier="")
    assert result.returncode == 1
    assert "64" in result.stderr
    big = tmp_path / "big"
    make_bsp(tmp_path, big / "bsp", external=10_000_000, emmc=10_000_000)
    assert publish(big, tmp_path, carrier="").returncode == 0


def test_a_tree_exactly_the_partition_size_is_accepted(tmp_path):
    inp = tmp_path / "input"
    make_bsp(tmp_path, inp / "bsp")
    size = (inp / "bsp" / STOCK).stat().st_size
    for layout in ("external-flash.xml.in", "internal-flash-emmc.xml"):
        (inp / "bsp" / layout).write_text(layout_xml(size))
    assert publish(inp, tmp_path, carrier="").returncode == 0


def test_a_file_that_is_not_a_tree_exits_1_naming_both_sizes(tmp_path):
    inp = tmp_path / "input"
    make_bsp(tmp_path, inp / "bsp")
    (inp / "bsp" / STOCK).write_bytes(b"not a device tree " * 4)
    result = publish(inp, tmp_path, carrier="")
    assert result.returncode == 1
    assert "not a valid device tree" in result.stderr
    assert str(72) in result.stderr
    assert str(KNOWN_SIZE) in result.stderr
    assert not (inp / OTA).exists()


def test_layouts_that_disagree_exit_1(tmp_path):
    inp = tmp_path / "input"
    make_bsp(tmp_path, inp / "bsp", emmc=KNOWN_SIZE * 2)
    result = publish(inp, tmp_path, carrier="")
    assert result.returncode == 1
    assert str(KNOWN_SIZE) in result.stderr
    assert str(KNOWN_SIZE * 2) in result.stderr
    assert not (inp / OTA).exists()


def test_a_layout_without_the_partition_exits_1(tmp_path):
    inp = tmp_path / "input"
    make_bsp(tmp_path, inp / "bsp")
    (inp / "bsp" / "external-flash.xml.in").write_text("<partition_layout/>")
    result = publish(inp, tmp_path, carrier="")
    assert result.returncode == 1
    assert "A_kernel-dtb" in result.stderr


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


def test_skipped_check_exits_1_when_the_update_tree_is_declared(tmp_path, rig):
    inp, _ = rig
    ota = write_manifest(tmp_path / "m-ota.json", ota=True)
    no_tools = run(inp, ota, env={"PATH": ""})
    assert no_tools.returncode == 1, no_tools.stdout
    assert "fdtoverlay" in no_tools.stderr
    bare = tmp_path / "bare"
    bare.mkdir()
    no_bsp = run(bare, ota)
    assert no_bsp.returncode == 1, no_bsp.stdout
    assert "BSP directory" in no_bsp.stderr
    lone = tmp_path / "lone"
    make_bsp(tmp_path, lone / "bsp")
    no_carrier = run(lone, ota)
    assert no_carrier.returncode == 1, no_carrier.stdout
    assert "carrier slot" in no_carrier.stderr
    assert not (lone / OTA).exists()


def test_no_carrier_in_the_manifest_runs_the_stage_without_one(tmp_path):
    inp = tmp_path / "input"
    make_bsp(tmp_path, inp / "bsp")
    result = run(inp, write_manifest(tmp_path / "m.json", carrier=""))
    assert result.returncode == 0, result.stderr
    assert "no carrier device tree in use; left unchanged" in result.stdout


def test_read_ota_image_declared_absent_and_unreadable(tmp_path):
    from avocado_tegraflash import EngineError
    from avocado_tegraflash.manifest import read_ota_image

    assert read_ota_image(write_manifest(tmp_path / "a.json", ota=True)) == OTA
    assert read_ota_image(write_manifest(tmp_path / "b.json")) == ""
    with pytest.raises(EngineError, match="cannot read manifest"):
        read_ota_image(tmp_path / "missing.json")
    (tmp_path / "bad.json").write_text("{")
    with pytest.raises(EngineError, match="cannot read manifest"):
        read_ota_image(tmp_path / "bad.json")
