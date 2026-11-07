"""read_manifest: absent or null values read as empty, as jq's `// empty` does."""

import dataclasses
import json

import pytest

from avocado_tegraflash import EngineError
from avocado_tegraflash.manifest import KEYS, Key, Manifest, read_manifest


def write(tmp_path, doc):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(doc))
    return path


def rootdisk(images=None, tegraflash=None):
    doc = {"storage_devices": {"rootdisk": {}}}
    if images is not None:
        doc["storage_devices"]["rootdisk"]["images"] = images
    if tegraflash is not None:
        doc["storage_devices"]["rootdisk"]["tegraflash"] = tegraflash
    return doc


def test_images_values_are_read_by_name(tmp_path):
    m = read_manifest(write(tmp_path, rootdisk(images={"rootfs": "r.erofs", "var": "v.btrfs"})))
    assert (m.rootfs, m.var) == ("r.erofs", "v.btrfs")


def test_tegraflash_scalar_and_lists_are_read(tmp_path):
    doc = rootdisk(
        tegraflash={"sd_device": "mmcblk0", "overlays": ["a.dtbo", "b.dtbo"], "dce_overlays": ["c.dtbo"]}
    )
    m = read_manifest(write(tmp_path, doc))
    assert (m.sd_device, m.overlays, m.dce_overlays) == ("mmcblk0", ("a.dtbo", "b.dtbo"), ("c.dtbo",))


def test_empty_object_reads_every_value_as_empty(tmp_path):
    m = read_manifest(write(tmp_path, {}))
    assert m == Manifest()


def test_default_manifest_has_empty_strings_and_empty_lists():
    m = Manifest()
    assert (m.rootfs, m.dtb, m.sd_device, m.overlays, m.dce_overlays) == ("", "", "", (), ())


def test_null_values_read_as_empty(tmp_path):
    doc = rootdisk(images={"rootfs": None, "dtb": None}, tegraflash={"overlays": None, "sd_device": None})
    m = read_manifest(write(tmp_path, doc))
    assert (m.rootfs, m.dtb, m.overlays, m.sd_device) == ("", "", (), "")


def test_null_section_reads_as_empty(tmp_path):
    m = read_manifest(write(tmp_path, rootdisk(images=None, tegraflash=None) | {"x": 1}))
    assert m.rootfs == ""


def test_null_rootdisk_reads_as_empty(tmp_path):
    m = read_manifest(write(tmp_path, {"storage_devices": {"rootdisk": None}}))
    assert m == Manifest()


def test_empty_overlay_list_reads_as_empty_tuple(tmp_path):
    m = read_manifest(write(tmp_path, rootdisk(tegraflash={"overlays": []})))
    assert m.overlays == ()


def test_unicode_value_survives(tmp_path):
    m = read_manifest(write(tmp_path, rootdisk(images={"rootfs": "ré.erofs"})))
    assert m.rootfs == "ré.erofs"


def test_unrelated_keys_are_ignored(tmp_path):
    doc = rootdisk(images={"rootfs": "r", "boot": {"out": "boot.img"}})
    assert read_manifest(write(tmp_path, doc)).rootfs == "r"


def test_every_declared_key_is_a_manifest_field():
    assert {k.name for k in KEYS} <= {f.name for f in dataclasses.fields(Manifest)}


def test_every_declared_key_round_trips(tmp_path):
    images = {k.name: f"{k.name}.img" for k in KEYS if k.section == "images"}
    tegraflash = {k.name: f"{k.name}.val" for k in KEYS if k.section == "tegraflash" and k.name == "sd_device"}
    m = read_manifest(write(tmp_path, rootdisk(images=images, tegraflash=tegraflash)))
    assert all(getattr(m, name) == f"{name}.img" for name in images)


def test_keys_cover_the_fourteen_oracle_reads():
    assert len(KEYS) == 14


def test_optional_keys_are_the_four_with_reasons():
    optional = {(k.section, k.name) for k in KEYS if k.optional}
    assert optional == {
        ("images", "dtb"),
        ("images", "bpmp_dtb"),
        ("tegraflash", "overlays"),
        ("tegraflash", "dce_overlays"),
    }


def test_every_optional_key_carries_a_reason():
    assert all(k.reason for k in KEYS if k.optional)


def test_key_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        KEYS[0].name = "x"  # type: ignore[misc]


def test_manifest_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        Manifest().rootfs = "x"  # type: ignore[misc]


def test_key_fields_are_positional_in_declared_order():
    assert Key("images", "rootfs", False, "") == Key(section="images", name="rootfs", optional=False, reason="")


def test_absent_file_is_refused(tmp_path):
    with pytest.raises(EngineError, match="manifest"):
        read_manifest(tmp_path / "missing.json")


def test_malformed_json_is_refused(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    with pytest.raises(EngineError, match="manifest"):
        read_manifest(path)


@pytest.mark.parametrize(
    "doc, key",
    [
        ([], "(top level)"),
        ("x", "(top level)"),
        ({"storage_devices": []}, "storage_devices"),
        ({"storage_devices": "x"}, "storage_devices"),
        ({"storage_devices": {"rootdisk": "x"}}, "storage_devices.rootdisk"),
        ({"storage_devices": {"rootdisk": ["a"]}}, "storage_devices.rootdisk"),
        (rootdisk(images="x"), "storage_devices.rootdisk.images"),
        (rootdisk(tegraflash=["x"]), "storage_devices.rootdisk.tegraflash"),
    ],
)
def test_a_non_object_where_an_object_is_required_is_refused_naming_the_path(tmp_path, doc, key):
    with pytest.raises(EngineError, match=key.replace("(", r"\(").replace(")", r"\)")):
        read_manifest(write(tmp_path, doc))


@pytest.mark.parametrize("name", ["overlays", "dce_overlays"])
@pytest.mark.parametrize("value", ["x.dtbo", {"a": "b"}, 5, True])
def test_a_non_list_overlays_value_is_refused_naming_the_key(tmp_path, name, value):
    with pytest.raises(EngineError, match=f"storage_devices.rootdisk.tegraflash.{name}"):
        read_manifest(write(tmp_path, rootdisk(tegraflash={name: value})))


@pytest.mark.parametrize("value", [{"a": "b"}, ["x"], True, False])
def test_a_container_or_boolean_where_a_string_is_required_is_refused(tmp_path, value):
    with pytest.raises(EngineError, match="storage_devices.rootdisk.images.rootfs"):
        read_manifest(write(tmp_path, rootdisk(images={"rootfs": value})))
    with pytest.raises(EngineError, match="storage_devices.rootdisk.tegraflash.sd_device"):
        read_manifest(write(tmp_path, rootdisk(tegraflash={"sd_device": value})))


@pytest.mark.parametrize("item", [["b"], True])
def test_a_container_or_boolean_inside_an_overlay_list_is_refused(tmp_path, item):
    with pytest.raises(EngineError, match="overlays"):
        read_manifest(write(tmp_path, rootdisk(tegraflash={"overlays": ["a.dtbo", item]})))


def test_absent_null_and_scalar_values_keep_their_defaults_and_str_conversion(tmp_path):
    doc = rootdisk(images={"rootfs": 7, "var": None}, tegraflash={"overlays": [1, "b.dtbo"]})
    m = read_manifest(write(tmp_path, doc))
    assert (m.rootfs, m.var, m.dtb, m.overlays, m.dce_overlays) == ("7", "", "", ("1", "b.dtbo"), ())
    assert read_manifest(write(tmp_path, {"storage_devices": None})) == Manifest()


def _mutant_reader(tmp_path, old, new):
    import importlib
    import shutil
    import sys
    from pathlib import Path

    import avocado_tegraflash

    pkg = Path(avocado_tegraflash.__file__).resolve().parent
    dest = tmp_path / "mut"
    shutil.copytree(pkg, dest / "avocado_tegraflash", ignore=shutil.ignore_patterns("__pycache__"))
    target = dest / "avocado_tegraflash" / "manifest.py"
    src = target.read_text()
    assert src.count(old) == 1
    target.write_text(src.replace(old, new))
    saved = {k: v for k, v in sys.modules.items() if k.startswith("avocado_tegraflash")}
    for k in saved:
        del sys.modules[k]
    sys.path.insert(0, str(dest))
    try:
        return importlib.import_module("avocado_tegraflash.manifest").read_manifest
    finally:
        sys.path.remove(str(dest))
        for k in [k for k in sys.modules if k.startswith("avocado_tegraflash")]:
            del sys.modules[k]
        sys.modules.update(saved)


@pytest.mark.parametrize(
    "old, doc",
    [
        ("if not isinstance(value, dict):", rootdisk(images="x")),
        ("if not isinstance(value, list):", rootdisk(tegraflash={"overlays": "x.dtbo"})),
        ("if isinstance(value, (dict, list, bool)):", rootdisk(images={"rootfs": {"a": 1}})),
        ("if isinstance(value, (dict, list, bool)):", rootdisk(images={"rootfs": True})),
    ],
)
def test_mutation_removing_a_type_check_lets_the_defective_manifest_through(tmp_path, old, doc):
    read = _mutant_reader(tmp_path, old, "if False:")
    path = write(tmp_path, doc)
    try:
        read(path)
    except Exception as exc:
        assert type(exc).__name__ != "EngineError", "mutant still refused"
