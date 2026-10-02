"""Tests for the closed strategy registry (arm, guard, layout)."""

import ast
import copy
import pathlib
import re

import pytest

from avocado_flash_remote import strategies
from avocado_flash_remote.strategies import StrategyError, validate

GOLDEN = pathlib.Path(__file__).parent / "golden" / "real-board-dry-run.txt"
DEVICE_SECTORS = 122314752
EFI = "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7"

_ROW = re.compile(
    r"^\s+/dev/mmcblk0p(\d+)\s+(\S+)\s+start=(\d+)\s+size=(\d+)\s+type=(\S+)$"
)


def jetson_table():
    parts = []
    text = GOLDEN.read_text()
    section = text.split("== images to write ==")[0]
    for line in section.splitlines():
        m = _ROW.match(line)
        if m:
            parts.append(
                {
                    "number": int(m.group(1)),
                    "name": m.group(2),
                    "start": int(m.group(3)),
                    "size": int(m.group(4)),
                    "type_guid": m.group(5),
                }
            )
    return parts


def jetson_layout():
    return {
        "sector_size": 512,
        "first_lba": 40,
        "last_lba": DEVICE_SECTORS - 34,
        "device_sectors": DEVICE_SECTORS,
        "table": jetson_table(),
    }


# --- registry shape ---------------------------------------------------------


def test_registry_names():
    assert strategies.names("arm") == ["none", "uefi-bootnext"]
    assert strategies.names("guard") == ["boot-arg", "none"]
    assert strategies.names("layout") == ["explicit-table"]


@pytest.mark.parametrize(
    "kind,name",
    [("arm", "kexec"), ("guard", "magic"), ("layout", "sfdisk-dump")],
)
def test_unknown_name_per_kind(kind, name):
    with pytest.raises(StrategyError) as exc:
        validate(kind, name, {})
    msg = str(exc.value)
    assert kind in msg and name in msg
    for allowed in strategies.names(kind):
        assert allowed in msg


def test_unknown_kind():
    with pytest.raises(StrategyError) as exc:
        validate("transport", "ssh", {})
    assert "transport" in str(exc.value)


@pytest.mark.parametrize("name", ["os.system", "../x", "pkg.mod:Class", "__import__"])
def test_profile_names_are_never_resolved_as_code(name):
    for kind in ("arm", "guard", "layout"):
        with pytest.raises(StrategyError) as exc:
            validate(kind, name, {})
        assert name in str(exc.value)


def test_module_has_no_dynamic_code_loading():
    src = pathlib.Path(strategies.__file__).read_text()
    tree = ast.parse(src)
    banned = {"importlib", "__import__", "exec", "eval", "compile", "getattr"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in banned, node.id
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names]
            if isinstance(node, ast.ImportFrom):
                mods.append(node.module or "")
            assert not any("importlib" in m for m in mods)
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"import_module", "__import__"}


# --- arm --------------------------------------------------------------------

def test_arm_uefi_bootnext_valid():
    p = {"entry_label": "UEFI eMMC Device"}
    assert validate("arm", "uefi-bootnext", p) == p


def test_arm_uefi_bootnext_missing_required():
    with pytest.raises(StrategyError) as exc:
        validate("arm", "uefi-bootnext", {})
    assert "entry_label" in str(exc.value)


@pytest.mark.parametrize("empty", ["", "   "])
def test_arm_uefi_bootnext_rejects_an_empty_entry_label(empty):
    with pytest.raises(StrategyError) as exc:
        validate("arm", "uefi-bootnext", {"entry_label": empty})
    assert "entry_label" in str(exc.value)


@pytest.mark.parametrize("gone", ["label", "loader_path", "boot_args"])
def test_arm_uefi_bootnext_rejects_the_removed_create_parameters(gone):
    with pytest.raises(StrategyError) as exc:
        validate("arm", "uefi-bootnext", {"entry_label": "x", gone: "y"})
    assert gone in str(exc.value)


def test_arm_wrong_type():
    with pytest.raises(StrategyError) as exc:
        validate("arm", "uefi-bootnext", {"entry_label": 5})
    assert "entry_label" in str(exc.value)


def test_arm_bool_is_not_str_or_int():
    with pytest.raises(StrategyError) as exc:
        validate("arm", "uefi-bootnext", {"entry_label": True})
    assert "entry_label" in str(exc.value)


def test_unknown_param():
    with pytest.raises(StrategyError) as exc:
        validate("arm", "uefi-bootnext", {"entry_label": "x", "zzz": 1})
    assert "zzz" in str(exc.value)


def test_arm_none_takes_no_params():
    assert validate("arm", "none", {}) == {}
    with pytest.raises(StrategyError) as exc:
        validate("arm", "none", {"entry_label": "x"})
    assert "entry_label" in str(exc.value)


def test_params_must_be_plain_json_values():
    with pytest.raises(StrategyError) as exc:
        validate("arm", "uefi-bootnext", {"entry_label": object()})
    assert "entry_label" in str(exc.value)


def test_params_must_be_mapping():
    with pytest.raises(StrategyError):
        validate("arm", "none", ["x"])


# --- guard ------------------------------------------------------------------


def test_guard_boot_arg_valid():
    p = {"argument": "modprobe.blacklist=nvme", "partitions": ["A_kernel", "B_kernel"]}
    assert validate("guard", "boot-arg", p) == p


def test_guard_boot_arg_partitions_wrong_item_type():
    with pytest.raises(StrategyError) as exc:
        validate("guard", "boot-arg", {"argument": "a", "partitions": ["x", 3]})
    assert "partitions" in str(exc.value)


def test_guard_boot_arg_missing_partitions():
    with pytest.raises(StrategyError) as exc:
        validate("guard", "boot-arg", {"argument": "a"})
    assert "partitions" in str(exc.value)


@pytest.mark.parametrize("argument", ["", " ", "a b", "a\tb", "a\nb", " a"])
def test_guard_boot_arg_rejects_an_argument_that_is_not_one_token(argument):
    with pytest.raises(StrategyError, match="argument"):
        validate("guard", "boot-arg", {"argument": argument, "partitions": ["A_kernel"]})


@pytest.mark.parametrize(
    "partitions", [[], [""], ["A_kernel", ""], ["A_kernel", "A_kernel"]]
)
def test_guard_boot_arg_rejects_an_empty_or_duplicated_partition_list(partitions):
    with pytest.raises(StrategyError, match="partitions"):
        validate("guard", "boot-arg", {"argument": "a=b", "partitions": partitions})


def test_guard_none():
    assert validate("guard", "none", {}) == {}


# --- layout -----------------------------------------------------------------


def test_jetson_table_is_sixteen_partitions():
    assert len(jetson_table()) == 16


def test_layout_valid_jetson_table():
    out = validate("layout", "explicit-table", jetson_layout())
    assert out["last_lba"] == 122314718
    assert len(out["table"]) == 16


def test_layout_sector_size_defaults_to_512():
    p = jetson_layout()
    del p["sector_size"]
    assert validate("layout", "explicit-table", p)["sector_size"] == 512


def test_layout_does_not_mutate_input():
    p = jetson_layout()
    before = copy.deepcopy(p)
    validate("layout", "explicit-table", p)
    assert p == before


def _layout_with(mutate):
    p = jetson_layout()
    mutate(p)
    return p


def test_layout_overlap():
    def m(p):
        p["table"][1]["start"] = p["table"][0]["start"] + 1

    with pytest.raises(StrategyError) as exc:
        validate("layout", "explicit-table", _layout_with(m))
    assert "overlap" in str(exc.value)


def test_layout_partition_outside_range_after_last():
    def m(p):
        p["table"][-1]["size"] += 10

    with pytest.raises(StrategyError) as exc:
        validate("layout", "explicit-table", _layout_with(m))
    assert "last_lba" in str(exc.value)


def test_layout_partition_before_first_lba():
    def m(p):
        p["table"][0]["start"] = 8

    with pytest.raises(StrategyError) as exc:
        validate("layout", "explicit-table", _layout_with(m))
    assert "first_lba" in str(exc.value)


def test_layout_wrong_last_lba():
    def m(p):
        p["last_lba"] = DEVICE_SECTORS - 1

    with pytest.raises(StrategyError) as exc:
        validate("layout", "explicit-table", _layout_with(m))
    assert "last_lba" in str(exc.value)


def test_layout_bad_guid():
    def m(p):
        p["table"][0]["type_guid"] = "not-a-guid"

    with pytest.raises(StrategyError) as exc:
        validate("layout", "explicit-table", _layout_with(m))
    assert "type_guid" in str(exc.value)


def test_layout_duplicate_numbers():
    def m(p):
        p["table"][1]["number"] = p["table"][0]["number"]

    with pytest.raises(StrategyError) as exc:
        validate("layout", "explicit-table", _layout_with(m))
    assert "number" in str(exc.value)


def test_layout_duplicate_names():
    def m(p):
        p["table"][1]["name"] = p["table"][0]["name"]

    with pytest.raises(StrategyError) as exc:
        validate("layout", "explicit-table", _layout_with(m))
    assert "name" in str(exc.value)


def test_layout_empty_name():
    def m(p):
        p["table"][0]["name"] = ""

    with pytest.raises(StrategyError) as exc:
        validate("layout", "explicit-table", _layout_with(m))
    assert "name" in str(exc.value)


def test_layout_nonpositive_size():
    def m(p):
        p["table"][0]["size"] = 0

    with pytest.raises(StrategyError) as exc:
        validate("layout", "explicit-table", _layout_with(m))
    assert "size" in str(exc.value)


def test_layout_partition_wrong_type_and_unknown_field():
    def m(p):
        p["table"][0]["start"] = "40"

    with pytest.raises(StrategyError) as exc:
        validate("layout", "explicit-table", _layout_with(m))
    assert "start" in str(exc.value)

    def m2(p):
        p["table"][0]["extra"] = 1

    with pytest.raises(StrategyError) as exc:
        validate("layout", "explicit-table", _layout_with(m2))
    assert "extra" in str(exc.value)


def test_layout_missing_partition_field():
    def m(p):
        del p["table"][0]["type_guid"]

    with pytest.raises(StrategyError) as exc:
        validate("layout", "explicit-table", _layout_with(m))
    assert "type_guid" in str(exc.value)


def test_layout_missing_required_and_empty_table():
    p = jetson_layout()
    del p["device_sectors"]
    with pytest.raises(StrategyError) as exc:
        validate("layout", "explicit-table", p)
    assert "device_sectors" in str(exc.value)

    p = jetson_layout()
    p["table"] = []
    with pytest.raises(StrategyError) as exc:
        validate("layout", "explicit-table", p)
    assert "table" in str(exc.value)


# --- optional per-partition uuid ---------------------------------------------

JETSON_UUID = "4D21B016-B534-45C2-A9FB-5C16E091FD2D"
PROFILE_JSON = (
    pathlib.Path(strategies.__file__).parent
    / "profiles"
    / "jetson-agx-orin-j5012.json"
)


def _set_uuid(number_to_uuid):
    def m(p):
        for part in p["table"]:
            if part["number"] in number_to_uuid:
                part["uuid"] = number_to_uuid[part["number"]]

    return m


def test_layout_uuid_is_optional():
    out = validate("layout", "explicit-table", jetson_layout())
    assert all("uuid" not in p for p in out["table"])


@pytest.mark.parametrize("value", [JETSON_UUID, JETSON_UUID.lower()])
def test_layout_uuid_accepted_any_case(value):
    out = validate(
        "layout", "explicit-table", _layout_with(_set_uuid({16: value}))
    )
    assert [p["uuid"] for p in out["table"] if "uuid" in p] == [value]


@pytest.mark.parametrize(
    "value",
    [
        "4D21B016-B534-45C2-A9FB-5C16E091FD2",
        "4D21B016-B534-45C2-A9FB-5C16E091FD2DD",
        "4D21B016-B534-45C2-A9FB-5C16E091FD2G",
        "4D21B016B53445C2A9FB5C16E091FD2D",
        "",
    ],
)
def test_layout_uuid_malformed_rejected(value):
    with pytest.raises(StrategyError) as exc:
        validate("layout", "explicit-table", _layout_with(_set_uuid({16: value})))
    assert "uuid" in str(exc.value)


def test_layout_uuid_wrong_type_rejected():
    with pytest.raises(StrategyError):
        validate("layout", "explicit-table", _layout_with(_set_uuid({16: 5})))


def test_layout_uuid_duplicate_rejected_case_insensitive():
    with pytest.raises(StrategyError) as exc:
        validate(
            "layout",
            "explicit-table",
            _layout_with(_set_uuid({1: JETSON_UUID, 16: JETSON_UUID.lower()})),
        )
    assert "uuid" in str(exc.value)


def test_jetson_profile_partition_16_carries_uuid():
    import json

    table = json.loads(PROFILE_JSON.read_text())["layout"]["params"]["table"]
    carried = {p["number"]: p["uuid"] for p in table if "uuid" in p}
    assert carried == {16: JETSON_UUID}


def test_jetson_profile_sfdisk_input_equals_golden_without_uuids_argument():
    import json

    from avocado_flash_remote import layout

    params = json.loads(PROFILE_JSON.read_text())["layout"]["params"]
    got = layout.sfdisk_input(params, "/dev/mmcblk0")
    lines = GOLDEN.read_text().splitlines()
    start = lines.index("    label: gpt")
    block = []
    for line in lines[start:]:
        if not line.startswith("    "):
            break
        block.append(line[4:])
    assert got == "\n".join(block) + "\n"


# ---- 5.33: partition names and UUIDs are interpolated into an sfdisk script ----


@pytest.mark.parametrize("name", ['a"b', "a b", "a\nb", "a;b", "a$b", "x" * 37, "", "a/b", "ünï"])
def test_layout_partition_name_charset_is_strict(name):
    def m(p):
        p["table"][0]["name"] = name

    with pytest.raises(StrategyError, match="name"):
        validate("layout", "explicit-table", _layout_with(m))


def test_layout_shipped_style_names_still_pass():
    def m(p):
        p["table"][0]["name"] = "A_kernel.v+2-x"

    validate("layout", "explicit-table", _layout_with(m))


@pytest.mark.parametrize("first", [-1, 0, 33])
def test_layout_first_lba_must_clear_the_gpt_header(first):
    def m(p):
        p["first_lba"] = first

    with pytest.raises(StrategyError, match="first_lba"):
        validate("layout", "explicit-table", _layout_with(m))


def test_layout_last_lba_must_exceed_first_lba():
    def m(p):
        p["first_lba"] = p["last_lba"]
        p["table"] = [dict(p["table"][0], start=p["last_lba"], size=1)]

    with pytest.raises(StrategyError, match="first_lba|last_lba"):
        validate("layout", "explicit-table", _layout_with(m))


def test_layout_guid_with_a_trailing_newline_is_refused():
    def m(p):
        p["table"][0]["uuid"] = "4D21B016-B534-45C2-A9FB-5C16E091FD2D\n"

    with pytest.raises(StrategyError, match="uuid"):
        validate("layout", "explicit-table", _layout_with(m))
