import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

from avocado_flash_boards import (
    NVIDIA_VENDOR,
    Board,
    BoardError,
    all_boards,
    lookup,
    parse_recovery_id,
    FAMILIES,
    family_vendors,
    load,
)

VENDORS = {"tegra": "0955"}
EVIDENCE = "lsusb on the bench Orin Nano showed 0955:7523 NVIDIA Corp. APX"


def test_registry_has_the_seven_jetson_machines():
    names = sorted(b.machine for b in all_boards())
    assert names == [
        "avocado-icam-540",
        "avocado-jetson-agx-orin",
        "avocado-jetson-agx-thor",
        "avocado-jetson-orin-nano",
        "avocado-jetson-orin-nx",
        "avocado-recomputer-j301x",
        "avocado-recomputer-j401x",
    ]
    assert {b.family for b in all_boards()} == {"tegra"}


def test_only_the_orin_nano_has_a_recovery_id():
    ids = {b.machine: (b.rcm_id, b.rcm_evidence) for b in all_boards() if b.rcm_id}
    assert ids == {"avocado-jetson-orin-nano": ("0955:7523", EVIDENCE)}


def test_lookup_returns_the_board():
    b = lookup("avocado-jetson-orin-nano")
    assert b == Board("avocado-jetson-orin-nano", "tegra", "0955:7523", EVIDENCE)


def test_lookup_unknown_names_machine_and_points_at_boards():
    with pytest.raises(BoardError) as e:
        lookup("avocado-nope")
    assert "avocado-nope" in str(e.value)
    assert "avocado-flash boards" in str(e.value)


def test_board_is_frozen():
    with pytest.raises(AttributeError):
        lookup("avocado-jetson-orin-nano").rcm_id = "0955:0000"


def test_duplicate_machine_is_rejected():
    a = Board("avocado-x", "tegra")
    with pytest.raises(BoardError, match="duplicate.*avocado-x"):
        load([a, Board("avocado-x", "tegra")], VENDORS)


def test_tegra_id_with_foreign_vendor_is_rejected():
    with pytest.raises(BoardError, match="avocado-x"):
        load([Board("avocado-x", "tegra", "1234:7523", EVIDENCE)], VENDORS)


@pytest.mark.parametrize("bad", ["0955:75", "0955-7523", "0955:ABCD", "0955:7523 ", "", "xxxx:yyyy"])
def test_malformed_id_is_rejected(bad):
    with pytest.raises(BoardError, match="avocado-x"):
        load([Board("avocado-x", "tegra", bad, EVIDENCE)], VENDORS)


@pytest.mark.parametrize("ev", [None, "", "   "])
def test_id_without_evidence_is_rejected(ev):
    with pytest.raises(BoardError, match="evidence"):
        load([Board("avocado-x", "tegra", "0955:7523", ev)], VENDORS)


def test_valid_input_is_accepted():
    boards = [Board("avocado-x", "tegra", "0955:7523", EVIDENCE), Board("avocado-y", "tegra")]
    assert load(boards, VENDORS) == {b.machine: b for b in boards}


@pytest.mark.parametrize("text, want", [("0955:7523", "0955:7523"), ("  0955:7523\n", "0955:7523"), ("0955:ABCD", "0955:abcd")])
def test_parse_recovery_id_accepts(text, want):
    assert parse_recovery_id(text) == want


@pytest.mark.parametrize("text", ["", "0955", "0955:752", "0955:75231", "g955:7523", "0955 7523"])
def test_parse_recovery_id_refuses_malformed(text):
    with pytest.raises(BoardError, match="vendor:product hex pair"):
        parse_recovery_id(text)


def test_parse_recovery_id_refuses_foreign_vendor():
    with pytest.raises(BoardError, match=f"vendor must be {NVIDIA_VENDOR}"):
        parse_recovery_id("1234:7523")


def test_unknown_family_is_a_load_error_even_with_a_plausible_id():
    with pytest.raises(BoardError, match=r"avocado-x.*unknown family 'tegar'"):
        load([Board("avocado-x", "tegar", "1234:5678", EVIDENCE)], VENDORS)


def test_unknown_family_is_refused_without_a_recovery_id():
    with pytest.raises(BoardError, match="avocado-x"):
        load([Board("avocado-x", "tegar")], VENDORS)


def test_a_family_module_without_a_vendor_is_refused():
    import types

    vendorless = types.ModuleType("avocado_flash_boards.nova")
    vendorless.BOARDS = []
    with pytest.raises(BoardError, match="family nova"):
        family_vendors([vendorless])


def test_every_shipped_family_exports_a_vendor_and_boards():
    vendors = family_vendors(FAMILIES)
    assert vendors == VENDORS
    assert all(isinstance(f.BOARDS, list) for f in FAMILIES)


def test_a_bad_registry_surfaces_as_a_board_error_not_at_import(monkeypatch):
    import avocado_flash_boards as boards_pkg

    monkeypatch.setattr(boards_pkg.tegra, "BOARDS", [Board("avocado-x", "tegar")])
    boards_pkg._registry.cache_clear()
    try:
        with pytest.raises(BoardError, match="avocado-x"):
            all_boards()
    finally:
        monkeypatch.undo()
        boards_pkg._registry.cache_clear()


ENGINE = Path(__file__).resolve().parents[3] / "meta-avocado-nvidia" / "stone" / "tegra" / "avocado_tegraflash"


def _engine_recovery_pids():
    """The engine's RECOVERY_PIDS, loaded by path: the two pytest trees stay separate.

    usb.py uses a relative import, so the package is loaded under a private name
    and removed again afterwards.
    """
    name = "_engine_pids_probe"
    spec = importlib.util.spec_from_file_location(
        name, ENGINE / "__init__.py", submodule_search_locations=[str(ENGINE)]
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[name] = package
    try:
        spec.loader.exec_module(package)
        return importlib.import_module(f"{name}.usb").RECOVERY_PIDS
    finally:
        for key in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
            del sys.modules[key]


def _unrecognised(boards, pids):
    """Messages for registry recovery ids whose product id the engine would not treat as recovery."""
    return [
        f"{b.machine}: recovery id {b.rcm_id} has product id {b.rcm_id.split(':')[1]}, missing from"
        f" RECOVERY_PIDS in {ENGINE.name}/usb.py"
        for b in boards
        if b.rcm_id and b.rcm_id.split(":")[1] not in pids
    ]


def test_every_registry_recovery_id_is_recognised_by_the_engine():
    assert _unrecognised(all_boards(), _engine_recovery_pids()) == []


def test_an_unrecognised_recovery_id_is_reported_with_board_and_product_id():
    board = Board("avocado-x", "tegra", "0955:7a7a", "seen on the bench")
    [message] = _unrecognised([board], _engine_recovery_pids())
    assert "avocado-x" in message and "7a7a" in message and "usb.py" in message
