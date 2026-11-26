"""Tests carrying the boot overlay deviations, driven through `main` under --prepare-only.

The oracle never reads the boot overlay lists and has no device-tree replay, so
no parity case can carry these; each test asserts the engine's own refusal or
modification instead.
"""

import pytest

from test_cli_boot_overlays import (  # noqa: F401  (_require_dtc is an autouse fixture)
    CAM1,
    CARVEOUTS,
    DANGLING_DTS,
    DYNAMIC,
    DYNAMIC_DTS,
    OPTEE,
    SUMMARY,
    DtcRunner,
    _require_dtc,
    dirs,
    go,
    stage_bsp,
    work_tree,
)
from test_cli_flow import make_rig

NO_BOARD_CONTACT = {"lsusb", "boardctl", "initrd-flash"}


@pytest.mark.deviation("boot-overlay-list-unreadable-refused")
@pytest.mark.parametrize("name", ["BOOTCONTROL_OVERLAYS", "PLUGIN_MANAGER_OVERLAYS", "OVERLAY_DTB_FILE"])
def test_unreadable_list_assignment_is_refused_naming_file_line_and_name(tmp_path, capsys, name):
    rig = make_rig(tmp_path)
    bsp, _ = dirs(rig)
    (bsp / "flashvars").write_text(f'{name}="a.dtbo"\n{name}+=",b.dtbo"\n')
    rc, out, err = go(rig, capsys, argv=())
    assert rc == 1
    assert "flashvars" in err and "line 2" in err and name in err
    assert SUMMARY not in out
    assert NO_BOARD_CONTACT & set(rig.runner.tools()) == set()


@pytest.mark.deviation("devkit-camera-fragments-stripped")
def test_carrier_tree_without_a_carrier_list_strips_the_camera_fragments(tmp_path, capsys):
    rig = make_rig(tmp_path, carrier={"CARRIER_LABEL": "Test Carrier"}, runner=DtcRunner())
    bsp, _ = stage_bsp(tmp_path, rig)
    original = (bsp / DYNAMIC).read_bytes()
    rc, out, err = go(rig, capsys)
    assert (rc, err) == (0, "")
    assert f"devkit camera fragments: removed fragment-camera0 from {DYNAMIC}" in out
    assert f"devkit camera fragments: removed fragment-camera1 from {DYNAMIC}" in out
    assert f"devkit camera fragments: dropped {CAM1} from PLUGIN_MANAGER_OVERLAYS" in out
    top = {node for node in work_tree(rig, DYNAMIC) if node.count("/") == 1}
    assert not any(n.startswith("/fragment-camera") for n in top)
    assert f'PLUGIN_MANAGER_OVERLAYS="{CARVEOUTS},{DYNAMIC},{OPTEE}"' in (rig.work / "flashvars").read_text()
    assert (bsp / DYNAMIC).read_bytes() == original


@pytest.mark.deviation("modified-boot-overlay-refused")
def test_kept_fragment_referencing_a_removed_node_is_refused(tmp_path, capsys):
    rig = make_rig(tmp_path, carrier={"CARRIER_LABEL": "Test Carrier"}, runner=DtcRunner())
    stage_bsp(tmp_path, rig, dynamic_dts=DANGLING_DTS)
    rc, out, err = go(rig, capsys)
    assert rc == 1
    assert "fragment@0" in err and "fragment-camera0" in err and "cam0-node" in err
    assert NO_BOARD_CONTACT & set(rig.runner.tools()) == set()
    assert SUMMARY not in out


@pytest.mark.deviation("modified-boot-overlay-refused")
def test_stripped_dynamic_overlay_that_fails_to_apply_is_refused(tmp_path, capsys):
    rig = make_rig(tmp_path, carrier={"CARRIER_LABEL": "Test Carrier"}, runner=DtcRunner())
    stage_bsp(tmp_path, rig, dynamic_dts=DYNAMIC_DTS.replace('"/cam"', '"/nowhere"'))
    rc, out, err = go(rig, capsys)
    assert rc == 1
    assert DYNAMIC in err and "failed to apply" in err
    assert NO_BOARD_CONTACT & set(rig.runner.tools()) == set()
