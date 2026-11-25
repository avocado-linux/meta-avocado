import shutil
import subprocess

import pytest

from avocado_tegraflash import EngineError
from avocado_tegraflash.bootoverlays import CarrierShape, EffectiveView
from avocado_tegraflash.devkitcamera import apply_policy
from avocado_tegraflash.fdtreplay import read_tree
from avocado_tegraflash.runner import SubprocessRunner

PACKAGE_HINT = "install the device-tree-compiler package (dtc, fdtget, fdtput, fdtoverlay)"
DYNAMIC = "tegra234-p3737-0000+p3701-0000-dynamic.dtbo"
CARVEOUTS = "tegra234-carveouts.dtbo"
OPTEE = "tegra-optee.dtbo"
CAM_OVERLAY = "tegra234-p3737-camera-imx219-overlay.dtbo"
CAM_OVERLAY_2 = "tegra234-p3737-camera-imx477-overlay.dtbo"
LIST = [CARVEOUTS, DYNAMIC, CAM_OVERLAY, OPTEE, CAM_OVERLAY_2]

BASE = """/dts-v1/;
/ {
    compatible = "test,board";
    ext_a: ext-a { };
    ext_b: ext-b { };
};
"""

# fragment-camera1 points at fragment-camera0 locally and at both base labels
# through __fixups__, so the strip has to cope with an entry that vanishes
# wholly (ext_b) and one that is shared with a kept fragment (ext_a).
DYNAMIC_DTS = """/dts-v1/;
/plugin/;
/ {
    fragment@0 {
        target-path = "/";
        __overlay__ {
            keep_label: kept {
                self = <&keep_label>;
                link = <&ext_a>;
            };
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

DANGLING_DTS = DYNAMIC_DTS.replace("self = <&keep_label>;", "self = <&cam0>;")

NO_CAMERA_DTS = """/dts-v1/;
/plugin/;
/ {
    fragment@0 {
        target-path = "/";
        __overlay__ {
            only: only-node { a = <1>; };
        };
    };
};
"""


@pytest.fixture(autouse=True)
def _require_dtc():
    # A missing tool must fail the suite, not skip it: a skip would let CI go green without testing the strip.
    for tool in ("dtc", "fdtget", "fdtput", "fdtoverlay"):
        if shutil.which(tool) is None:
            pytest.fail(f"{tool} not found on PATH: {PACKAGE_HINT}")


def compile_dts(path, text, *, overlay=False):
    src = path.with_suffix(".dts")
    src.write_text(text)
    argv = ["dtc", "-q", "-I", "dts", "-O", "dtb"]
    if overlay:
        argv.append("-@")
    subprocess.run([*argv, "-o", str(path), str(src)], check=True)
    return path


@pytest.fixture
def work(tmp_path):
    return tmp_path / "work"


def make_work(work, dynamic_text=DYNAMIC_DTS, plugin_list=LIST, flashvars_prefix="export "):
    work.mkdir()
    compile_dts(work / DYNAMIC, dynamic_text, overlay=True)
    for name in (CARVEOUTS, OPTEE, CAM_OVERLAY, CAM_OVERLAY_2):
        (work / name).write_bytes(b"x")
    flashvars = (
        'BOOTCONTROL_OVERLAYS="bc.dtbo"\n'
        f'{flashvars_prefix}PLUGIN_MANAGER_OVERLAYS="{",".join(plugin_list)}"\n'
        "OTHER=1\n"
    )
    (work / "flashvars").write_text(flashvars)
    return EffectiveView.work_dir(str(work))


def run_policy(view, *, shape=CarrierShape.A, carrier_list_set=False):
    logged = []
    modified = apply_policy(view, view.overlay_lists(), shape, carrier_list_set, SubprocessRunner(), logged.append)
    return modified, logged


def flashvars_list(work):
    for line in (work / "flashvars").read_text().split("\n"):
        if "PLUGIN_MANAGER_OVERLAYS=" in line:
            return line.split('"')[1].split(",")
    raise AssertionError("assignment missing")


def test_stripped_overlay_has_no_camera_node_symbol_or_fixup(work):
    view = make_work(work)

    modified, _ = run_policy(view)

    tree = read_tree(work / DYNAMIC)
    assert modified is True
    assert [n for n in tree if "camera" in n] == []
    assert [p for p, v in tree["/__symbols__"].items() if b"fragment-camera" in v] == []
    assert all(b"fragment-camera" not in v for v in tree.get("/__fixups__", {}).values())
    assert [n for n in tree if n.startswith("/__local_fixups__/fragment-camera")] == []
    assert "/fragment@0/__overlay__/kept" in tree


def test_fixup_entry_shared_with_a_kept_fragment_keeps_only_the_kept_reference(work):
    view = make_work(work)

    run_policy(view)

    fixups = read_tree(work / DYNAMIC)["/__fixups__"]
    assert fixups["ext_a"] == b"/fragment@0/__overlay__/kept:link:0\x00"
    assert "ext_b" not in fixups


def test_stripped_overlay_still_applies_onto_a_base_tree(work, tmp_path):
    view = make_work(work)
    base = compile_dts(tmp_path / "base.dtb", BASE, overlay=True)
    run_policy(view)
    out = tmp_path / "out.dtb"

    done = subprocess.run(
        ["fdtoverlay", "-i", str(base), "-o", str(out), str(work / DYNAMIC)],
        capture_output=True,
        text=True,
    )

    assert done.returncode == 0, done.stderr
    tree = read_tree(out)
    assert "/kept" in tree and "/cam0-node" not in tree and "/cam1-node" not in tree


def test_kept_fragment_referencing_a_camera_node_is_refused_naming_both(work):
    view = make_work(work, DANGLING_DTS)
    before = (work / DYNAMIC).read_bytes()

    with pytest.raises(EngineError) as info:
        run_policy(view)

    message = str(info.value)
    assert "fragment@0" in message and "self" in message and "fragment-camera0" in message
    assert (work / DYNAMIC).read_bytes() == before
    assert flashvars_list(work) == LIST


def test_kept_fixup_label_resolving_into_a_removed_fragment_is_refused(work):
    view = make_work(work)
    # cam0 is a symbol of the overlay itself; a kept fixup that names it is a reference into the removed node.
    runner = SubprocessRunner()
    status, out = runner.capture(
        ["fdtput", "-t", "s", str(work / DYNAMIC), "/__fixups__", "cam0", "/fragment@0/__overlay__/kept:link:0"]
    )
    assert status == 0, out

    with pytest.raises(EngineError) as info:
        run_policy(view)

    assert "cam0" in str(info.value) and "fragment-camera0" in str(info.value)


def test_list_drops_camera_entries_in_order_and_keeps_carveouts_and_optee(work):
    view = make_work(work)

    run_policy(view)

    assert flashvars_list(work) == [CARVEOUTS, DYNAMIC, OPTEE]


def test_rewritten_assignment_keeps_its_export_prefix_and_other_lines(work):
    view = make_work(work)

    run_policy(view)

    lines = (work / "flashvars").read_text().split("\n")
    assert lines[0] == 'BOOTCONTROL_OVERLAYS="bc.dtbo"'
    assert lines[1] == f'export PLUGIN_MANAGER_OVERLAYS="{CARVEOUTS},{DYNAMIC},{OPTEE}"'
    assert lines[2] == "OTHER=1"


def test_rewritten_assignment_without_export_stays_without_it(work):
    view = make_work(work, flashvars_prefix="")

    run_policy(view)

    assert (work / "flashvars").read_text().split("\n")[1].startswith("PLUGIN_MANAGER_OVERLAYS=")


def test_one_log_line_per_removed_fragment_and_dropped_overlay(work):
    view = make_work(work)

    _, logged = run_policy(view)

    assert len([m for m in logged if "removed fragment-camera" in m]) == 2
    assert [m for m in logged if CAM_OVERLAY in m and "dropped" in m]
    assert [m for m in logged if CAM_OVERLAY_2 in m and "dropped" in m]
    assert len(logged) == 4


def test_carrier_set_list_leaves_both_files_byte_identical(work):
    view = make_work(work)
    overlay_before = (work / DYNAMIC).read_bytes()
    vars_before = (work / "flashvars").read_bytes()

    modified, logged = run_policy(view, carrier_list_set=True)

    assert modified is False
    assert (work / DYNAMIC).read_bytes() == overlay_before
    assert (work / "flashvars").read_bytes() == vars_before
    assert logged == [
        "devkit camera fragments: the carrier sets its own PLUGIN_MANAGER_OVERLAYS; "
        "its list and the stock dynamic overlay are used unchanged"
    ]


def test_no_carrier_tree_leaves_both_files_byte_identical(work):
    view = make_work(work)
    overlay_before = (work / DYNAMIC).read_bytes()
    vars_before = (work / "flashvars").read_bytes()

    modified, logged = run_policy(view, shape=CarrierShape.NONE)

    assert modified is False
    assert (work / DYNAMIC).read_bytes() == overlay_before
    assert (work / "flashvars").read_bytes() == vars_before
    assert logged == ["devkit camera fragments: no carrier device tree in use; left unchanged"]


def test_overlay_without_camera_fragments_is_untouched_and_the_note_is_logged(work):
    view = make_work(work, NO_CAMERA_DTS, plugin_list=[CARVEOUTS, DYNAMIC, OPTEE])
    overlay_before = (work / DYNAMIC).read_bytes()
    vars_before = (work / "flashvars").read_bytes()

    modified, logged = run_policy(view)

    assert modified is False
    assert (work / DYNAMIC).read_bytes() == overlay_before
    assert (work / "flashvars").read_bytes() == vars_before
    assert logged == [f"devkit camera fragments: none found in {DYNAMIC}; overlay left unchanged"]


def test_strip_never_writes_through_a_link_to_the_bsp(work, tmp_path):
    view = make_work(work)
    bsp = tmp_path / "bsp-copy.dtbo"
    shutil.move(work / DYNAMIC, bsp)
    (work / DYNAMIC).symlink_to(bsp)
    bsp_before = bsp.read_bytes()

    run_policy(view)

    assert bsp.read_bytes() == bsp_before
    assert not (work / DYNAMIC).is_symlink()
    assert [n for n in read_tree(work / DYNAMIC) if "camera" in n] == []


def test_dynamic_overlay_named_like_a_camera_entry_is_refused(work):
    name = "x-camera-y-dynamic.dtbo"
    work.mkdir()
    (work / name).write_bytes(b"x")
    (work / "flashvars").write_text(f'PLUGIN_MANAGER_OVERLAYS="{name}"\n')
    view = EffectiveView.work_dir(str(work))

    with pytest.raises(EngineError, match="x-camera-y-dynamic.dtbo"):
        run_policy(view)
    assert (work / "flashvars").read_text() == f'PLUGIN_MANAGER_OVERLAYS="{name}"\n'
