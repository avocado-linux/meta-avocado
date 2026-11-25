"""The boot overlay stage through `main`: lists, camera policy and replay, before any board contact."""

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from avocado_tegraflash.cli import main
from avocado_tegraflash.fdtreplay import read_tree
from avocado_tegraflash.runner import SubprocessRunner
from test_cli_flow import Call, FakeRunner, make_rig

STOCK = "stock.dtb"
OTHER_SKU = "other-sku.dtb"
DYNAMIC = "tegra234-p3737-0000+p3701-0000-dynamic.dtbo"
CARVEOUTS = "tegra234-carveouts.dtbo"
OPTEE = "tegra-optee.dtbo"
CAM1 = "tegra234-p3737-camera-imx219-overlay.dtbo"
CAM2 = "tegra234-p3737-camera-imx477-overlay.dtbo"
BOOTCONTROL = "bootcontrol.dtbo"
PLUGINS = [CARVEOUTS, DYNAMIC, CAM1, OPTEE, CAM2]
SUMMARY = "Boot overlays at flash:"

BASE_DTS = """/dts-v1/;
/ {
    compatible = "test,board";
    cam { channels = <4>; };
    ext_a: ext-a { };
    ext_b: ext-b { };
};
"""
# The carrier integrator lowers the channel count the stock tree sets.
CARRIER_TREE_DTS = BASE_DTS.replace("channels = <4>;", "channels = <2>;")

DYNAMIC_DTS = """/dts-v1/;
/plugin/;
/ {
    fragment@0 {
        target-path = "/cam";
        __overlay__ {
            channels = <4>;
        };
    };
    fragment-camera0 {
        target-path = "/";
        __overlay__ {
            cam0: cam0-node {
                link = <&ext_a>;
            };
        };
    };
    fragment-camera1 {
        target-path = "/";
        __overlay__ {
            cam1-node {
                peer = <&cam0>;
                link = <&ext_b>;
            };
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
FLASHVARS = (
    'BOOTCONTROL_OVERLAYS="{bc}"\n'
    'PLUGIN_MANAGER_OVERLAYS="{plugins}"\n'
    'OVERLAY_DTB_FILE=""\n'
)


@dataclass
class DtcRunner(FakeRunner):
    """Run the tree tools for real and the rest through the recording fake."""

    capsys: object = None
    before_wait: str | None = None
    real: SubprocessRunner = field(default_factory=SubprocessRunner)

    def capture(self, argv, **kw):
        tool = Path(argv[0]).name
        if tool in ("fdtoverlay", "fdtput"):
            self.calls.append(Call("capture", list(argv), kw.get("cwd"), kw.get("env")))
            return self.real.capture(argv, **kw)
        if tool == "lsusb" and self.before_wait is None and self.capsys is not None:
            self.before_wait = self.capsys.readouterr().out
        return super().capture(argv, **kw)


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


def dirs(rig):
    data = Path(rig.environ["AVOCADO_STONE_DATA_DIR"])
    images = json.loads((data / "manifest.json").read_text())["storage_devices"]["rootdisk"]["images"]
    return data / images["tegraflash_bsp"].lstrip("/"), data / images["tegraflash_carrier_bsp"].lstrip("/")


def stage_bsp(
    tmp_path,
    rig,
    *,
    dynamic_dts=DYNAMIC_DTS,
    plugins=PLUGINS,
    broken=(),
    carrier_trees=((STOCK, CARRIER_TREE_DTS),),
):
    """Stock tree, overlays and lists in the BSP, and the carrier's own trees in its slot."""
    bsp, slot = dirs(rig)
    dtb(tmp_path, bsp / STOCK, BASE_DTS)
    shutil.copyfile(bsp / STOCK, bsp / f"kernel_{STOCK}")
    env = bsp / ".env.initrd-flash"
    env.write_text(env.read_text() + f'DTBFILE="{STOCK}"\n')
    for name in (BOOTCONTROL, CARVEOUTS, OPTEE, CAM1, CAM2):
        if name in broken:
            (bsp / name).write_bytes(b"not a device tree")
        else:
            dtb(tmp_path, bsp / name, NOOP_DTS)
    dtb(tmp_path, bsp / DYNAMIC, dynamic_dts)
    (bsp / "flashvars").write_text(FLASHVARS.format(bc=BOOTCONTROL, plugins=",".join(plugins)))
    for name, text in carrier_trees:
        dtb(tmp_path, slot / name, text)
    return bsp, slot


def go(rig, capsys, argv=("--prepare-only",)):
    rc, out, err = rig.go(main, capsys, argv=argv)
    return rc, out, err


def work_tree(rig, name):
    return read_tree(rig.work / name)


def test_three_lists_are_printed_with_the_carrier_rewrite_of_the_plugin_list(tmp_path, capsys):
    rig = make_rig(tmp_path, carrier={"CARRIER_FV_PLUGIN_MANAGER_OVERLAYS": CARVEOUTS})
    bsp, _ = dirs(rig)
    (bsp / "flashvars").write_text(FLASHVARS.format(bc=BOOTCONTROL, plugins=f"{CARVEOUTS},{CAM1}"))
    rc, out, _ = go(rig, capsys)
    assert rc == 0
    assert f"  BOOTCONTROL_OVERLAYS: {BOOTCONTROL}\n" in out
    assert f"  PLUGIN_MANAGER_OVERLAYS: {CARVEOUTS}\n" in out
    assert CAM1 not in out
    assert "  OVERLAY_DTB_FILE: <unset>\n" in out


def test_unreadable_plugin_assignment_is_refused_with_no_board_contact(tmp_path, capsys):
    rig = make_rig(tmp_path)
    bsp, _ = dirs(rig)
    (bsp / "flashvars").write_text('PLUGIN_MANAGER_OVERLAYS="a.dtbo"\nPLUGIN_MANAGER_OVERLAYS+=",b.dtbo"\n')
    rc, out, err = go(rig, capsys, argv=())
    assert rc == 1
    assert "PLUGIN_MANAGER_OVERLAYS" in err and "line 2" in err
    assert SUMMARY not in out
    assert {"lsusb", "boardctl", "initrd-flash"} & set(rig.runner.tools()) == set()


def test_no_flashvars_prints_the_lists_as_unknown_and_skips_the_rest(tmp_path, capsys):
    rig = make_rig(tmp_path, drop=("flashvars",))
    rc, out, _ = go(rig, capsys)
    assert rc == 0
    assert "unknown (the BSP has no flashvars)" in out
    assert "replay" not in out and "devkit camera fragments" not in out


def test_unset_dtbfile_skips_the_replay_without_refusing(tmp_path, capsys):
    rig = make_rig(tmp_path)
    rc, out, _ = go(rig, capsys)
    assert rc == 0
    assert "Boot overlay replay skipped: DTBFILE is not set" in out
    assert "devkit camera fragments: no carrier device tree in use; left unchanged" in out


def test_absent_flashed_tree_skips_the_replay_without_refusing(tmp_path, capsys):
    rig = make_rig(tmp_path)
    bsp, _ = dirs(rig)
    env = bsp / ".env.initrd-flash"
    env.write_text(env.read_text() + 'DTBFILE="missing.dtb"\n')
    rc, out, _ = go(rig, capsys)
    assert rc == 0
    assert "Boot overlay replay skipped" in out and "missing.dtb" in out


def test_shape_a_carrier_strips_camera_fragments_and_warns_about_the_reset(tmp_path, capsys):
    rig = make_rig(tmp_path, carrier={"CARRIER_LABEL": "Test Carrier"}, runner=DtcRunner())
    bsp, _ = stage_bsp(tmp_path, rig)
    original_dynamic = (bsp / DYNAMIC).read_bytes()
    original_flashvars = (bsp / "flashvars").read_bytes()
    rc, out, err = go(rig, capsys)
    assert (rc, err) == (0, "")
    assert f"devkit camera fragments: removed fragment-camera0 from {DYNAMIC}" in out
    assert f"devkit camera fragments: removed fragment-camera1 from {DYNAMIC}" in out
    assert f"devkit camera fragments: dropped {CAM1} from PLUGIN_MANAGER_OVERLAYS" in out
    warning = next(line for line in out.splitlines() if "integrator-set property" in line)
    assert warning.startswith("  WARNING:")
    for part in ("/cam", "channels", f"{DYNAMIC}", "0x00000002", "0x00000004"):
        assert part in warning
    names = {node for node in work_tree(rig, DYNAMIC) if node.count("/") == 1}
    assert not any(n.startswith("/fragment-camera") for n in names)
    assert "/fragment@0" in names
    assert f'PLUGIN_MANAGER_OVERLAYS="{CARVEOUTS},{DYNAMIC},{OPTEE}"' in (rig.work / "flashvars").read_text()
    # The data directory's BSP is never edited.
    assert (bsp / DYNAMIC).read_bytes() == original_dynamic
    assert (bsp / "flashvars").read_bytes() == original_flashvars


def test_replay_reads_the_work_directory_overlay_not_the_bsp_original(tmp_path, capsys):
    rig = make_rig(tmp_path, carrier={"CARRIER_LABEL": "Test Carrier"}, runner=DtcRunner())
    stage_bsp(tmp_path, rig)
    go(rig, capsys)
    replayed = [c for c in rig.runner.named("fdtoverlay") if c.argv[-1].endswith(DYNAMIC)]
    assert [c.argv[-1] for c in replayed] == [str(rig.work / DYNAMIC)]


def test_the_flashed_tree_is_the_carrier_copy_not_the_bsp_kernel_prefixed_one(tmp_path, capsys):
    rig = make_rig(tmp_path, carrier={"CARRIER_LABEL": "Test Carrier"}, runner=DtcRunner())
    stage_bsp(tmp_path, rig)
    _, out, _ = go(rig, capsys)
    first = rig.runner.named("fdtoverlay")[0]
    assert str(rig.work / f"kernel_{STOCK}") not in first.argv
    assert "integrator-set property" in out


def test_shape_b_redirect_replays_the_redirected_tree(tmp_path, capsys):
    rig = make_rig(tmp_path, carrier={"CARRIER_ENV_DTBFILE": OTHER_SKU}, runner=DtcRunner())
    stage_bsp(tmp_path, rig, carrier_trees=((OTHER_SKU, CARRIER_TREE_DTS),))
    rc, out, _ = go(rig, capsys)
    assert rc == 0
    assert "integrator-set property" in out
    assert f"removed fragment-camera0 from {DYNAMIC}" in out


def test_dangling_camera_reference_is_refused_under_prepare_only(tmp_path, capsys):
    rig = make_rig(tmp_path, carrier={"CARRIER_LABEL": "Test Carrier"}, runner=DtcRunner())
    stage_bsp(tmp_path, rig, dynamic_dts=DANGLING_DTS)
    rc, out, err = go(rig, capsys)
    assert rc == 1
    assert "fragment@0" in err and "fragment-camera0" in err and "cam0-node" in err
    assert {"lsusb", "boardctl", "initrd-flash"} & set(rig.runner.tools()) == set()
    assert SUMMARY not in out


def test_stripped_dynamic_overlay_that_fails_to_apply_is_refused(tmp_path, capsys):
    rig = make_rig(tmp_path, carrier={"CARRIER_LABEL": "Test Carrier"}, runner=DtcRunner())
    stage_bsp(tmp_path, rig, dynamic_dts=DYNAMIC_DTS.replace('"/cam"', '"/nowhere"'))
    rc, _, err = go(rig, capsys)
    assert rc == 1
    assert DYNAMIC in err and "failed to apply" in err


def test_unrelated_overlay_failure_after_a_list_only_trim_does_not_refuse(tmp_path, capsys):
    rig = make_rig(tmp_path, carrier={"CARRIER_LABEL": "Test Carrier"}, runner=DtcRunner())
    stage_bsp(tmp_path, rig, dynamic_dts=NOOP_DTS, broken=(CARVEOUTS,))
    rc, out, _ = go(rig, capsys)
    assert rc == 0
    assert f"dropped {CAM1} from PLUGIN_MANAGER_OVERLAYS" in out
    assert f"  WARNING: boot overlay {CARVEOUTS} failed to apply in the replay" in out


def test_unmodified_overlay_that_fails_to_apply_only_warns(tmp_path, capsys):
    carrier = {"CARRIER_FV_PLUGIN_MANAGER_OVERLAYS": f"{CARVEOUTS},{DYNAMIC}"}
    rig = make_rig(tmp_path, carrier=carrier, runner=DtcRunner())
    stage_bsp(tmp_path, rig, broken=(CARVEOUTS,))
    rc, out, _ = go(rig, capsys)
    assert rc == 0
    assert f"  WARNING: boot overlay {CARVEOUTS} failed to apply in the replay" in out
    assert "the carrier sets its own PLUGIN_MANAGER_OVERLAYS" in out


def test_summary_is_printed_before_the_recovery_wait(tmp_path, capsys):
    runner = DtcRunner(capsys=capsys)
    rig = make_rig(tmp_path, carrier={"CARRIER_LABEL": "Test Carrier"}, runner=runner)
    stage_bsp(tmp_path, rig)
    rc, out, _ = go(rig, capsys, argv=())
    assert rc == 0
    assert runner.before_wait is not None
    assert runner.before_wait.count(SUMMARY) == 2
    assert out.count(SUMMARY) == 0


def test_prepare_only_prints_the_summary_in_both_places(tmp_path, capsys):
    rig = make_rig(tmp_path)
    _, out, _ = go(rig, capsys)
    assert out.count(SUMMARY) == 2
