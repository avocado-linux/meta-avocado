"""Boot overlay lists: grammar, chain order, layered view, carrier-tree shapes, report."""

import pytest

from avocado_tegraflash import EngineError
from avocado_tegraflash.bootoverlays import (
    CarrierShape,
    EffectiveView,
    OverlayLists,
    carrier_redirect,
    carrier_sets_plugin_list,
    detect_carrier_tree,
    format_lists,
    overlay_chain,
    parse_overlay_lists,
    read_overlay_lists,
)
from avocado_tegraflash.carrier import carrier_patches


def _parse(text):
    return parse_overlay_lists(text, "flashvars")


def _refusal(text):
    with pytest.raises(EngineError) as exc:
        _parse(text)
    return str(exc.value)


def test_quoted_forms_and_split_with_empty_items_dropped():
    lists = _parse('BOOTCONTROL_OVERLAYS="a.dtbo,,b.dtbo,"\nPLUGIN_MANAGER_OVERLAYS=\'p.dtbo\'\nOVERLAY_DTB_FILE=x.dtbo\n')
    assert lists == OverlayLists(("a.dtbo", "b.dtbo"), ("p.dtbo",), ("x.dtbo",))


def test_last_assignment_wins_with_export_and_unquoted_mixed():
    lists = _parse(
        'PLUGIN_MANAGER_OVERLAYS="first.dtbo"\n'
        "export PLUGIN_MANAGER_OVERLAYS=second.dtbo\n"
        'export PLUGIN_MANAGER_OVERLAYS="third.dtbo,fourth.dtbo"\n'
    )
    assert lists.plugin_manager == ("third.dtbo", "fourth.dtbo")


def test_never_assigned_is_unset_and_empty_assignment_is_empty():
    lists = _parse('BOOTCONTROL_OVERLAYS=""\nOTHER=1\n')
    assert lists.bootcontrol == ()
    assert lists.plugin_manager is None
    assert lists.extra is None


def test_comment_lines_are_ignored_even_when_they_mention_a_name():
    lists = _parse('# PLUGIN_MANAGER_OVERLAYS+=evil\n   # OVERLAY_DTB_FILE=$(x)\nOVERLAY_DTB_FILE="ok.dtbo"\n')
    assert lists.extra == ("ok.dtbo",)
    assert lists.plugin_manager is None


def test_names_inside_longer_identifiers_are_not_the_list_names():
    lists = _parse('MY_OVERLAY_DTB_FILE=$(x)\nOVERLAY_DTB_FILE_OLD="y"\nBOOTCONTROL_OVERLAYS="a"\n')
    assert lists.extra is None
    assert lists.bootcontrol == ("a",)


@pytest.mark.parametrize(
    "line",
    [
        'PLUGIN_MANAGER_OVERLAYS+="x.dtbo"',
        'PLUGIN_MANAGER_OVERLAYS="$(ls)"',
        'PLUGIN_MANAGER_OVERLAYS="${X}"',
        'PLUGIN_MANAGER_OVERLAYS="`ls`"',
        'PLUGIN_MANAGER_OVERLAYS="unterminated',
        '  PLUGIN_MANAGER_OVERLAYS="x"',
        'PLUGIN_MANAGER_OVERLAYS="x" && true',
        'echo "$PLUGIN_MANAGER_OVERLAYS"',
        "PLUGIN_MANAGER_OVERLAYS=x y",
    ],
)
def test_other_uses_of_a_name_are_refused_with_file_line_and_name(line):
    msg = _refusal(f"OK=1\n{line}\n")
    assert "flashvars" in msg
    assert "line 2" in msg
    assert "PLUGIN_MANAGER_OVERLAYS" in msg


def test_refusal_names_the_right_list_and_line_number():
    msg = _refusal('BOOTCONTROL_OVERLAYS="a"\n\n\nOVERLAY_DTB_FILE=$(x)\n')
    assert "line 4" in msg
    assert "OVERLAY_DTB_FILE" in msg


def test_read_overlay_lists_reads_file_and_names_it_in_refusals(tmp_path):
    good = tmp_path / "flashvars"
    good.write_text('OVERLAY_DTB_FILE="o.dtbo"\n')
    assert read_overlay_lists(str(good)).extra == ("o.dtbo",)
    bad = tmp_path / "bad"
    bad.write_text("OVERLAY_DTB_FILE+=o\n")
    with pytest.raises(EngineError, match="bad"):
        read_overlay_lists(str(bad))


def test_chain_is_bootcontrol_plugin_then_extra():
    assert overlay_chain(OverlayLists(("b",), ("p1", "p2"), ("x",))) == ["b", "p1", "p2", "x"]


def test_chain_with_empty_plugin_list_keeps_bootcontrol_then_extra():
    assert overlay_chain(OverlayLists(("b",), (), ("x",))) == ["b", "x"]
    assert overlay_chain(OverlayLists(("b",), None, ("x",))) == ["b", "x"]


def test_chain_with_everything_unset_is_empty():
    assert overlay_chain(OverlayLists(None, None, None)) == []


def test_work_dir_view_resolves_names_in_the_work_dir(tmp_path):
    (tmp_path / "flashvars").write_text('OVERLAY_DTB_FILE="o.dtbo"\n')
    view = EffectiveView.work_dir(str(tmp_path))
    assert view.resolve("o.dtbo") == str(tmp_path / "o.dtbo")
    assert view.flashvars_text() == 'OVERLAY_DTB_FILE="o.dtbo"\n'
    assert view.overlay_lists().extra == ("o.dtbo",)


def _layered(tmp_path, bsp_files, carrier_files, env_text=""):
    bsp = tmp_path / "bsp"
    slot = tmp_path / "slot"
    bsp.mkdir()
    slot.mkdir()
    for name, text in bsp_files.items():
        (bsp / name).write_text(text)
    for name, text in carrier_files.items():
        (slot / name).write_text(text)
    patches = carrier_patches(env_text)
    return EffectiveView.layered(str(bsp), str(slot), patches), bsp, slot


def test_layered_view_prefers_the_carrier_slot_over_the_bsp(tmp_path):
    view, bsp, slot = _layered(tmp_path, {"flashvars": "", "a.dtb": "bsp", "b.dtb": "bsp"}, {"a.dtb": "slot"})
    assert view.resolve("a.dtb") == str(slot / "a.dtb")
    assert view.resolve("b.dtb") == str(bsp / "b.dtb")
    assert view.resolve("missing.dtb") is None


def test_layered_flashvars_carrier_slot_copy_wins_over_bsp(tmp_path):
    view, _, _ = _layered(tmp_path, {"flashvars": 'OVERLAY_DTB_FILE="bsp"\n'}, {"flashvars": 'OVERLAY_DTB_FILE="slot"\n'})
    assert view.overlay_lists().extra == ("slot",)


def test_layered_flashvars_gets_patches_in_memory_in_order_last_wins(tmp_path):
    env = 'CARRIER_FV_PLUGIN_MANAGER_OVERLAYS="one.dtbo"\nCARRIER_FV_PLUGIN_MANAGER_OVERLAYS="two.dtbo,three.dtbo"\nCARRIER_ENV_DTBFILE=x\n'
    view, bsp, _ = _layered(
        tmp_path,
        {"flashvars": 'KEEP=1\nPLUGIN_MANAGER_OVERLAYS="old.dtbo"\nPLUGIN_MANAGER_OVERLAYS_X=1\n'},
        {},
        env,
    )
    text = view.flashvars_text()
    assert text == 'KEEP=1\nPLUGIN_MANAGER_OVERLAYS="two.dtbo,three.dtbo"\nPLUGIN_MANAGER_OVERLAYS_X=1\n'
    assert (bsp / "flashvars").read_text().startswith("KEEP=1\nPLUGIN_MANAGER_OVERLAYS=\"old.dtbo\"")


def test_layered_patch_rewrites_every_matching_line_and_skips_absent_names(tmp_path):
    view, _, _ = _layered(
        tmp_path,
        {"flashvars": "A=1\nA=2\n"},
        {},
        'CARRIER_FV_A="z"\nCARRIER_FV_NOPE="q"\n',
    )
    assert view.flashvars_text() == 'A="z"\nA="z"\n'


def test_layered_without_any_flashvars_is_refused(tmp_path):
    view, _, _ = _layered(tmp_path, {}, {})
    with pytest.raises(EngineError, match="flashvars"):
        view.flashvars_text()


def _slot(tmp_path, files):
    slot = tmp_path / "carrier"
    slot.mkdir()
    for name in files:
        (slot / name).write_text("x")
    return str(slot)


BASE = "tegra234-p3737-0000+p3701-0000-nv.dtb"


def test_detect_none(tmp_path):
    assert detect_carrier_tree(_slot(tmp_path, ["other.dtb"]), BASE, "CARRIER_LABEL=x\n") is CarrierShape.NONE


def test_detect_shape_a_slot_ships_the_base_tree(tmp_path):
    assert detect_carrier_tree(_slot(tmp_path, [BASE]), BASE, "") is CarrierShape.A


def test_detect_shape_b_redirect_to_another_tree(tmp_path):
    env = "CARRIER_ENV_DTBFILE=other-sku.dtb\n"
    assert detect_carrier_tree(_slot(tmp_path, []), BASE, env) is CarrierShape.B
    assert carrier_redirect(env, BASE) == "other-sku.dtb"


def test_detect_both(tmp_path):
    env = 'CARRIER_ENV_DTBFILE="other-sku.dtb"\n'
    assert detect_carrier_tree(_slot(tmp_path, [BASE]), BASE, env) is CarrierShape.BOTH


def test_redirect_to_the_base_name_itself_is_not_a_redirect(tmp_path):
    env = f"CARRIER_ENV_DTBFILE={BASE}\n"
    assert carrier_redirect(env, BASE) is None
    assert detect_carrier_tree(_slot(tmp_path, []), BASE, env) is CarrierShape.NONE


def test_last_column_zero_redirect_wins_and_indented_lines_do_not_count(tmp_path):
    env = "CARRIER_ENV_DTBFILE=first.dtb\n  CARRIER_ENV_DTBFILE=indented.dtb\nCARRIER_ENV_DTBFILE=last.dtb\n"
    assert carrier_redirect(env, BASE) == "last.dtb"
    assert carrier_redirect("CARRIER_ENV_DTBFILE=first.dtb\nCARRIER_ENV_DTBFILE=" + BASE + "\n", BASE) is None


def test_carrier_sets_plugin_list():
    assert carrier_sets_plugin_list(carrier_patches('CARRIER_FV_PLUGIN_MANAGER_OVERLAYS=""\n')) is True
    assert carrier_sets_plugin_list(carrier_patches("CARRIER_FV_OVERLAY_DTB_FILE=x\nCARRIER_ENV_PLUGIN_MANAGER_OVERLAYS=y\n")) is False
    assert carrier_sets_plugin_list([]) is False


def test_format_lists_heading_then_one_line_per_list_in_chain_order():
    lines = format_lists(OverlayLists(("b.dtbo",), None, ("x.dtbo", "y.dtbo")))
    assert "UEFI applies" in lines[0]
    assert "every boot" in lines[0]
    assert lines[1:] == [
        "  BOOTCONTROL_OVERLAYS: b.dtbo",
        "  PLUGIN_MANAGER_OVERLAYS: <unset>",
        "  OVERLAY_DTB_FILE: x.dtbo,y.dtbo",
    ]


def test_format_lists_prints_an_empty_list_as_unset():
    assert format_lists(OverlayLists((), (), ()))[1:] == [
        "  BOOTCONTROL_OVERLAYS: <unset>",
        "  PLUGIN_MANAGER_OVERLAYS: <unset>",
        "  OVERLAY_DTB_FILE: <unset>",
    ]
